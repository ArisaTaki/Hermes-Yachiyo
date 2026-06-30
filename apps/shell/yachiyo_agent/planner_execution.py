"""Convert runtime planner decisions into existing tool request payloads."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .app_name_hints import is_legacy_app_name_hint, legacy_app_name_hint
from .capture_plan_hints import capture_tool_preview
from .data_analysis_plan_hints import data_source_kind_hint
from .clipboard_plan_hints import clipboard_tool_preview
from .desktop_plan_hints import app_control_tool_candidates, media_app_query_search_plan, media_tool_preview
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


def planner_execution_tool_requests(
    requests: Iterable[Mapping[str, Any]],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    """Normalize direct requests into the execution shape used by Chat entrypoints."""

    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    normalized_requests = [dict(request) for request in requests if isinstance(request, Mapping)]
    if not normalized_requests:
        return []
    if not _has_discovered_app_foreground_verification_chain(normalized_requests):
        normalized_requests = _collapse_app_foreground_direct_requests(normalized_requests, allowed)
    normalized_requests = _drop_redundant_post_inspect_app_prepare_requests(normalized_requests)
    return _drop_redundant_execution_verification_requests(normalized_requests)


def planner_orchestration_requests(
    prompt: str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    decision = RuntimePlanner().decision(
        prompt,
        allowed_tools=["workflow.run", "group.run"],
        metadata=metadata,
    )
    intent_kind = str(decision.selected_intent.kind or "").strip()
    intent_inputs = decision.selected_intent.inputs if isinstance(decision.selected_intent.inputs, Mapping) else {}
    target_name = str(intent_inputs.get("target_name_hint") or "").strip()
    if intent_kind == "workflow_orchestration":
        if not target_name and not _looks_like_orchestration_action(prompt, "workflow"):
            return []
        return [_orchestration_request(decision, "workflow")]
    if intent_kind == "multi_agent":
        if not target_name and not _looks_like_orchestration_action(prompt, "group_run"):
            return []
        return [_orchestration_request(decision, "group_run")]
    return []


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
            step_ids=("inspect-report-file-scope", "gather-context"),
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
        direct_context_requests = _direct_communication_context_tool_requests(
            decision,
            allowed,
        )
        if direct_context_requests:
            return direct_context_requests
        context_requests = _context_source_tool_requests(
            decision,
            allowed,
            step_ids=("copy-selected-communication-context", "read-communication-context"),
            planning_reason="planner_prefetch_communication_context",
        )
        if context_requests:
            return context_requests
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
    if decision.selected_intent.kind == "schedule":
        direct_requests = _direct_schedule_context_app_item_tool_requests(decision, allowed)
        if direct_requests:
            return direct_requests
        return _tool_requests_for_decision(decision, allowed)
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
    planning_reason: str = "planner_desktop_operation",
) -> dict[str, Any]:
    clean_payload = dict(payload)
    input_resolution = clean_payload.pop("_input_resolution", None)
    request = {
        "protocol": "json_fallback",
        "tool": tool,
        "input": clean_payload,
        "source": "runtime_planner",
        "planning_reason": planning_reason,
    }
    if isinstance(input_resolution, Mapping):
        request["input_resolution"] = dict(input_resolution)
    return request


def _orchestration_request(decision: Any, orchestration_kind: str) -> dict[str, Any]:
    intent = decision.selected_intent
    inputs = intent.inputs if isinstance(intent.inputs, Mapping) else {}
    target_name = str(inputs.get("target_name_hint") or "").strip()
    return {
        "kind": "orchestration",
        "orchestration_kind": orchestration_kind,
        "source": "runtime_planner",
        "planning_reason": f"planner_orchestration_{orchestration_kind}",
        "route_to_studio": bool(decision.plan.route_to_studio),
        "decision_id": str(decision.decision_id or ""),
        "plan_id": str(decision.plan.plan_id or ""),
        "intent_kind": str(intent.kind or ""),
        "input": {
            "objective": str(intent.user_goal or "").strip(),
            "title": str(intent.title or "").strip(),
            "target_name": target_name,
        },
    }


def _looks_like_orchestration_action(prompt: str, orchestration_kind: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    if re.search(
        r"(?:什么是|是什么|介绍|解释|说明|为什么|怎么设计|如何设计|不要|不用|无需|不需要|不使用|"
        r"what is|explain|describe|why|how should|do not|don't)",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    if orchestration_kind == "workflow":
        return bool(
            re.search(r"(?:workflow|flow|工作流|流程)", text, flags=re.IGNORECASE)
            and re.search(
                r"(?:运行|启动|执行|创建|新建|调试|跑|打开|run|start|execute|create|debug)",
                text,
                flags=re.IGNORECASE,
            )
        )
    return bool(
        re.search(
            r"(?:multi-agent|group|agents?|群组|小组|团队|多\s*agent|多Agent|协作|智能体|代理)",
            text,
            flags=re.IGNORECASE,
        )
        and re.search(
            r"(?:让|安排|派发|派活|委派|分配|指派|分别|各自|并行|协作|汇总|运行|启动|执行|"
            r"assign|dispatch|delegate|parallel|coordinate|run|start|execute)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _first_allowed(candidates: Iterable[str], allowed: set[str]) -> str:
    for candidate in candidates:
        tool_name = str(candidate or "").strip()
        if tool_name and tool_name in allowed:
            return tool_name
    return ""


def _desktop_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    if _has_unavailable_required_desktop_step(decision):
        return []
    requests: list[dict[str, Any]] = []
    for step in decision.plan.tool_plan.steps:
        if not _step_available(step):
            continue
        step_id = str(getattr(step, "step_id", "") or "").strip()
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        if not tool_name or tool_name not in allowed:
            continue
        if step_id in {"write-desktop-content-artifact", "open-selected-discovered-app"}:
            continue
        input_preview = getattr(step, "input_preview", None)
        payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        request = _request(
            tool_name,
            _desktop_request_payload(tool_name, payload),
            planning_reason=_desktop_step_planning_reason(step, tool_name),
        )
        if step_id == "read-desktop-content" or _desktop_observation_step_needs_model_followup(
            decision,
            step_id,
            tool_name,
        ) or _desktop_discovery_step_needs_model_followup(
            decision,
            step_id,
            tool_name,
        ):
            request["continue_to_model"] = True
        requests.append(request)
    if _weak_desktop_discovery_plan(decision, requests):
        return []
    return requests


def _has_unavailable_required_desktop_step(decision: Any) -> bool:
    plan = getattr(decision, "plan", None)
    tool_plan = getattr(plan, "tool_plan", None)
    steps = getattr(tool_plan, "steps", None)
    if not isinstance(steps, list):
        return False
    for step in steps:
        status = str(getattr(step, "status", "") or "").strip()
        if status != "unavailable":
            continue
        step_id = str(getattr(step, "step_id", "") or "").strip()
        capability_id = str(getattr(step, "capability_id", "") or "").strip()
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        if step_id == "verify-desktop-result":
            continue
        if not tool_name and step_id == "submit-foreground-ui":
            continue
        if capability_id in {"desktop.app_control", "desktop.ui_operation"}:
            return True
    return False


def _keep_direct_discovery_step(step: Any, tool_name: str) -> bool:
    if str(getattr(step, "step_id", "") or "").strip() != "discover-desktop-state":
        return False
    if tool_name != "desktop.list_apps":
        return False
    input_preview = getattr(step, "input_preview", None)
    payload = input_preview if isinstance(input_preview, Mapping) else {}
    query = str(payload.get("query") or "").strip()
    return bool(query)


_APP_FOREGROUND_DIRECT_OPERATION_SUFFIX = {
    "desktop.safe_shortcut": "safe_shortcut",
    "desktop.safe_key": "safe_key",
    "desktop.safe_scroll": "safe_scroll",
    "desktop.safe_click": "safe_click",
    "desktop.safe_type_text": "safe_type_text",
    "desktop.type_text": "safe_type_text",
    "desktop.hotkey": "hotkey",
    "desktop.click_ui_element": "click_ui_element",
    "desktop.type_into_ui_element": "type_into_ui_element",
}


def _collapse_app_foreground_direct_requests(
    requests: list[dict[str, Any]],
    allowed: set[str],
) -> list[dict[str, Any]]:
    collapsed: list[dict[str, Any]] = []
    index = 0
    while index < len(requests):
        request = requests[index]
        tool_name = str(request.get("tool") or "").strip()
        if tool_name not in {"app.open", "app.focus"}:
            collapsed.append(request)
            index += 1
            continue
        input_preview = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        app_name = str(input_preview.get("app_name") or "").strip()
        if not app_name:
            collapsed.append(request)
            index += 1
            continue
        operation_index = index + 1
        mode = "open" if tool_name == "app.open" else "focus"
        if (
            tool_name == "app.open"
            and operation_index < len(requests)
            and _same_app_control_request(requests[operation_index], "app.focus", app_name)
        ):
            operation_index += 1
        if operation_index >= len(requests):
            collapsed.append(request)
            index += 1
            continue
        operation = requests[operation_index]
        operation_tool = str(operation.get("tool") or "").strip()
        operation_input = operation.get("input") if isinstance(operation.get("input"), Mapping) else {}
        if (
            operation_tool == "desktop.safe_shortcut"
            and str(operation_input.get("action") or "").strip() == "find"
            and _has_later_search_submit(requests, operation_index)
        ):
            collapsed.append(request)
            index += 1
            continue
        suffix = _APP_FOREGROUND_DIRECT_OPERATION_SUFFIX.get(operation_tool, "")
        combined_tool = f"app.{mode}_and_{suffix}" if suffix else ""
        if not combined_tool or combined_tool not in allowed:
            collapsed.append(request)
            index += 1
            continue
        combined_payload = {"app_name": app_name, **dict(operation_input)}
        collapsed.append(
            _request(
                combined_tool,
                _desktop_request_payload(combined_tool, combined_payload),
                planning_reason=str(operation.get("planning_reason") or request.get("planning_reason") or "planner_desktop_operation"),
            )
        )
        index = operation_index + 1
    return collapsed


def _has_later_search_submit(
    requests: list[dict[str, Any]],
    operation_index: int,
) -> bool:
    for later_request in requests[operation_index + 1 :]:
        if str(later_request.get("tool") or "").strip() == "desktop.search_submit":
            return True
    return False


def _has_discovered_app_foreground_verification_chain(
    requests: list[dict[str, Any]],
) -> bool:
    if not any(str(request.get("source") or "").strip() == "runtime_planner" for request in requests):
        return False
    if not _has_unknown_discovered_app_query(requests):
        return False
    if not any(str(request.get("tool") or "").strip() == "desktop.list_apps" for request in requests):
        return False
    has_foreground_operation = False
    for index, request in enumerate(requests[:-1]):
        if str(request.get("tool") or "").strip() not in {
            "app.open",
            "app.focus",
            "desktop.open_app",
            "desktop.focus_app",
        }:
            continue
        for later_request in requests[index + 1 :]:
            if str(later_request.get("tool") or "").strip() in _APP_FOREGROUND_DIRECT_OPERATION_SUFFIX:
                has_foreground_operation = True
                break
        if has_foreground_operation:
            break
    if not has_foreground_operation:
        return False
    return any(
        str(request.get("tool") or "").strip() in _EXECUTION_VERIFICATION_TOOLS
        for request in requests
    )


def _has_unknown_discovered_app_query(requests: list[dict[str, Any]]) -> bool:
    for request in requests:
        if str(request.get("tool") or "").strip() != "desktop.list_apps":
            continue
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        query = str(payload.get("query") or "").strip()
        if query and not is_legacy_app_name_hint(query):
            return True
    return False


_EXECUTION_VERIFICATION_TOOLS = {
    "desktop.active_window",
    "desktop.running_apps",
    "desktop.windows",
    "desktop.list_windows",
    "desktop.ui_elements",
    "desktop.read_ui",
    "desktop.inspect_app",
    "desktop.verify",
    "screen.capture",
}

_EXECUTION_MUTATION_TOOLS = {
    "app.open",
    "app.focus",
    "desktop.open_app",
    "desktop.focus_app",
    "app.focus_window",
    "app.status",
    "app.show",
    "app.hide",
    "app.minimize",
    "app.quit",
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
    "desktop.shortcut",
    "desktop.hotkey",
    "desktop.type",
    "desktop.click_ui_element",
    "desktop.type_into_ui_element",
    "desktop.submit_foreground",
    "desktop.hide_app",
    "desktop.show_all_apps",
    "desktop.minimize_window",
    "desktop.close_window",
    "desktop.quit_app",
}


def _drop_redundant_execution_verification_requests(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(requests) <= 1:
        return requests
    filtered: list[dict[str, Any]] = []
    saw_mutation = False
    last_mutation_tool = ""
    for index, request in enumerate(requests):
        tool_name = str(request.get("tool") or "").strip()
        if (
            not saw_mutation
            and tool_name in _EXECUTION_VERIFICATION_TOOLS
            and not _keep_pre_mutation_verification_request(request)
            and any(
                str(item.get("tool") or "").strip() in _EXECUTION_MUTATION_TOOLS
                or _later_verification_supersedes(tool_name, str(item.get("tool") or "").strip())
                for item in requests[index + 1 :]
            )
        ):
            continue
        if (
            saw_mutation
            and tool_name in _EXECUTION_VERIFICATION_TOOLS
            and not _keep_post_mutation_verification_request(request, last_mutation_tool)
        ):
            continue
        filtered.append(request)
        if tool_name in _EXECUTION_MUTATION_TOOLS:
            saw_mutation = True
            last_mutation_tool = tool_name
    return filtered


def _drop_redundant_post_inspect_app_prepare_requests(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    inspect_app_name = ""
    for request in requests:
        tool_name = str(request.get("tool") or "").strip()
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        app_name = str(payload.get("app_name") or "").strip()
        if (
            tool_name in {"app.open", "app.focus", "desktop.open_app", "desktop.focus_app"}
            and app_name
            and inspect_app_name
            and app_name == inspect_app_name
        ):
            continue
        filtered.append(request)
        if tool_name == "desktop.inspect_app":
            focus_requested = payload.get("focus", True) is not False
            open_requested = payload.get("open_if_needed", True) is not False
            inspect_app_name = app_name if focus_requested or open_requested else ""
        elif tool_name not in {"app.open", "app.focus", "desktop.open_app", "desktop.focus_app"}:
            inspect_app_name = ""
    return filtered


def _keep_pre_mutation_verification_request(request: dict[str, Any]) -> bool:
    tool_name = str(request.get("tool") or "").strip()
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    if tool_name == "desktop.inspect_app":
        return bool(str(payload.get("app_name") or "").strip())
    if tool_name in {"desktop.windows", "desktop.list_windows", "desktop.verify"}:
        return bool(str(payload.get("app_name") or "").strip())
    if tool_name == "screen.capture":
        return bool(str(payload.get("reason") or "").strip())
    return False


def _keep_post_mutation_verification_request(
    request: dict[str, Any],
    previous_mutation_tool: str,
) -> bool:
    tool_name = str(request.get("tool") or "").strip()
    if tool_name in {"desktop.ui_elements", "desktop.read_ui", "desktop.windows", "desktop.list_windows"}:
        return True
    if tool_name in {"desktop.active_window", "desktop.running_apps"}:
        return previous_mutation_tool.startswith("app.") or previous_mutation_tool in {
            "desktop.hide_app",
            "desktop.show_all_apps",
            "desktop.minimize_window",
            "desktop.close_window",
            "desktop.quit_app",
        }
    if tool_name == "screen.capture":
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        return bool(str(payload.get("reason") or "").strip())
    return False


def _later_verification_supersedes(current_tool: str, later_tool: str) -> bool:
    if current_tool == later_tool:
        return False
    if later_tool in {"desktop.inspect_app", "desktop.verify"}:
        return True
    if current_tool == "screen.capture" and later_tool in {
        "desktop.ui_elements",
        "desktop.read_ui",
        "desktop.windows",
        "desktop.list_windows",
    }:
        return True
    if current_tool in {"desktop.running_apps", "desktop.active_window"} and later_tool in {
        "desktop.ui_elements",
        "desktop.read_ui",
        "desktop.windows",
        "desktop.list_windows",
    }:
        return True
    return False


def _same_app_control_request(request: dict[str, Any], tool_name: str, app_name: str) -> bool:
    if str(request.get("tool") or "").strip() != tool_name:
        return False
    input_preview = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    return str(input_preview.get("app_name") or "").strip() == app_name


def _direct_desktop_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    if _has_unavailable_required_desktop_step(decision):
        return []
    requests: list[dict[str, Any]] = []
    for step in decision.plan.tool_plan.steps:
        if not _step_available(step):
            continue
        step_id = str(getattr(step, "step_id", "") or "").strip()
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        if not tool_name or tool_name not in allowed:
            continue
        if step_id in {"write-desktop-content-artifact", "open-selected-discovered-app"}:
            continue
        if step_id == "discover-desktop-state" and not _keep_direct_discovery_step(step, tool_name):
            continue
        input_preview = getattr(step, "input_preview", None)
        payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        request = _request(
            tool_name,
            _desktop_request_payload(tool_name, payload),
            planning_reason=_desktop_step_planning_reason(step, tool_name),
        )
        if step_id == "read-desktop-content" or _desktop_observation_step_needs_model_followup(
            decision,
            step_id,
            tool_name,
        ) or _desktop_discovery_step_needs_model_followup(
            decision,
            step_id,
            tool_name,
        ):
            request["continue_to_model"] = True
        requests.append(request)
    if _weak_desktop_discovery_plan(decision, requests):
        return []
    return requests


def _step_available(step: Any) -> bool:
    return str(getattr(step, "status", "") or "").strip() != "unavailable"


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
        "app_preferences_hint",
    }
    return not any(inputs.get(key) for key in hint_keys)


def _desktop_step_planning_reason(step: Any, tool_name: str) -> str:
    if str(getattr(step, "step_id", "") or "").strip() == "read-desktop-content":
        return "planner_prefetch_desktop_content"
    input_preview = getattr(step, "input_preview", None)
    if "hotkey" in tool_name or (
        isinstance(input_preview, Mapping)
        and input_preview.get("key")
        and input_preview.get("modifiers") is not None
    ):
        return "planner_desktop_hotkey"
    return "planner_desktop_operation"


def _desktop_observation_step_needs_model_followup(
    decision: Any,
    step_id: str,
    tool_name: str,
) -> bool:
    if step_id not in {
        "capture-screen",
        "read-foreground-ui",
        "verify-desktop-result",
        "inspect-app",
    } and tool_name not in {
        "screen.capture",
        "desktop.ui_elements",
        "desktop.read_ui",
        "desktop.inspect_app",
        "desktop.verify",
    }:
        return False
    prompt = str(getattr(getattr(decision, "selected_intent", None), "user_goal", "") or "")
    if not prompt:
        return False
    inputs = getattr(getattr(decision, "selected_intent", None), "inputs", None)
    if (
        step_id == "verify-desktop-result"
        and isinstance(inputs, Mapping)
        and isinstance(inputs.get("creative_canvas_hint"), Mapping)
    ):
        return True
    if _desktop_observation_step_is_direct_readback(prompt, inputs):
        return False
    if _desktop_observation_prompt_needs_model_followup(prompt, inputs):
        return True
    if _desktop_verify_step_is_direct_control(step_id, tool_name, inputs):
        return False
    return False


def _desktop_observation_prompt_needs_model_followup(prompt: str, inputs: Any) -> bool:
    prompt_for_intent = prompt
    if isinstance(inputs, Mapping):
        compose_text = str(inputs.get("foreground_compose_text_hint") or "").strip()
        if compose_text:
            prompt_for_intent = prompt_for_intent.replace(compose_text, "")
    return bool(
        re.search(
            r"(?:判断|决定|分析|识别|告诉|说明|总结|摘要|下一步|该点哪里|该点哪个|"
            r"可以点|是否可以点|是否能点|如果能点|如果可以点|"
            r"最像|最接近|相关|有关|匹配|合适|适合|应该|可能|哪一个|哪项|哪条)",
            prompt_for_intent,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:judge|decide|analy[sz]e|identify|tell|explain|summari[sz]e|"
            r"determine|whether|what|which|where|should|next\s+step|closest|similar|"
            r"related|matching|appropriate|suitable|possible)\b",
            prompt_for_intent,
            flags=re.IGNORECASE,
        )
    )


def _desktop_verify_step_is_direct_control(
    step_id: str,
    tool_name: str,
    inputs: Any,
) -> bool:
    if step_id != "verify-desktop-result" or tool_name not in {
        "desktop.active_window",
        "desktop.ui_elements",
        "desktop.read_ui",
        "desktop.verify",
    }:
        return False
    if not isinstance(inputs, Mapping):
        return False
    if any(
        isinstance(inputs.get(key), Mapping)
        for key in (
            "creative_canvas_hint",
            "ui_inspection_hint",
            "screen_capture_hint",
            "app_capability_hint",
        )
    ):
        return False
    operation = str(inputs.get("operation_hint") or "").strip()
    return operation in {
        "",
        "open",
        "focus",
        "open_app",
        "focus_app",
        "hide_app",
        "minimize_window",
        "show_all_apps",
        "safe_shortcut",
        "safe_key",
        "safe_scroll",
    }


def _desktop_observation_step_is_direct_readback(
    prompt: str,
    inputs: Any,
) -> bool:
    if not isinstance(inputs, Mapping):
        return False
    if str(inputs.get("operation_hint") or "").strip() != "read_ui":
        return False
    if not isinstance(inputs.get("ui_inspection_hint"), Mapping):
        return False
    return bool(
        re.search(
            r"(?:有哪些|有什么|有什么可见|可见.*(?:按钮|控件|元素)|"
            r"(?:按钮|控件|元素).{0,8}(?:有哪些|有什么|可见))",
            prompt,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bwhat\s+(?:buttons?|controls?|elements?)\s+(?:are\s+)?(?:visible|shown|available)\b",
            prompt,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:visible|shown|available)\s+(?:buttons?|controls?|elements?)\b",
            prompt,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bwhere\s+(?:is|are)\s+(?:the\s+)?(?:.+?\s+)?(?:buttons?|controls?|elements?)\b",
            prompt,
            flags=re.IGNORECASE,
        )
    )


def _desktop_discovery_step_needs_model_followup(
    decision: Any,
    step_id: str,
    tool_name: str,
) -> bool:
    if tool_name != "desktop.list_apps":
        return False
    if step_id not in {"discover-desktop-state", "discover_apps-desktop-state"}:
        return False
    inputs = getattr(getattr(decision, "selected_intent", None), "inputs", None)
    if not isinstance(inputs, Mapping):
        return False
    if isinstance(inputs.get("app_capability_hint"), Mapping):
        return True
    if isinstance(inputs.get("generic_browser_discovery_hint"), Mapping):
        return True
    return any(
        str(getattr(step, "step_id", "") or "").strip() == "open-selected-discovered-app"
        for step in getattr(getattr(getattr(decision, "plan", None), "tool_plan", None), "steps", [])
    )


def _desktop_request_payload(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if tool_name.startswith("app.") or tool_name in {"desktop.open_app", "desktop.focus_app"}:
        return _canonicalize_app_payload(payload)
    if tool_name == "desktop.list_apps":
        query = str(payload.get("query") or "").strip()
        if not query:
            return payload
        canonical = _canonical_app_name(query) if not query.isascii() else query
        return {**payload, "query": canonical}
    if tool_name == "desktop.inspect_app":
        app_name = str(payload.get("app_name") or "").strip()
        request_payload = {
            key: payload[key]
            for key in ("open_if_needed", "focus", "role_filter", "limit")
            if key in payload and payload[key] not in (None, "")
        }
        if app_name:
            request_payload["app_name"] = _canonical_app_name(app_name)
        return request_payload
    if tool_name in {"desktop.running_apps", "desktop.active_window"}:
        return {}
    if tool_name == "screen.capture":
        reason = str(payload.get("reason") or "").strip()
        return {"reason": reason} if reason else {}
    if tool_name in {"desktop.ui_elements", "desktop.read_ui"}:
        request_payload = {
            key: payload[key]
            for key in ("app_name", "role_filter", "limit")
            if key in payload and payload[key] not in (None, "")
        }
        if request_payload.get("app_name"):
            request_payload["app_name"] = _canonical_app_name(
                str(request_payload["app_name"] or "")
            )
        return request_payload
    if tool_name in {"desktop.windows", "desktop.list_windows", "desktop.verify"}:
        app_name = str(payload.get("app_name") or "").strip()
        request_payload = {
            key: payload[key]
            for key in ("role_filter", "limit")
            if key in payload and payload[key] not in (None, "")
        }
        if app_name:
            request_payload["app_name"] = _canonical_app_name(app_name)
        return request_payload
    return payload


def _canonicalize_app_payload(payload: dict[str, Any]) -> dict[str, Any]:
    app_name = str(payload.get("app_name") or "").strip()
    if not app_name:
        return payload
    canonical = _canonical_app_name(app_name)
    canonical_payload = payload if canonical == app_name else {**payload, "app_name": canonical}
    target = str(canonical_payload.get("target") or "").strip()
    if canonical == "WeChat" and target in {"消息框", "聊天框"}:
        return {**canonical_payload, "target": "消息"}
    return canonical_payload


def _canonical_app_name(app_name: str) -> str:
    if str(app_name or "").strip() == "企业微信":
        return "企业微信"
    return legacy_app_name_hint(app_name)


def _data_analysis_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    app_requests = _data_analysis_spreadsheet_app_requests(decision, allowed)
    file_open_requests = _data_analysis_file_open_requests(decision, allowed)
    data_analyze_step = next(
        (
            item
            for item in decision.plan.tool_plan.steps
            if getattr(item, "tool_name", "") == "data.analyze"
        ),
        None,
    )
    if (
        data_analyze_step is not None
        and _step_available(data_analyze_step)
        and "data.analyze" in allowed
    ):
        input_preview = getattr(data_analyze_step, "input_preview", None)
        payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        if payload.get("path"):
            request_input = {
                "path": str(payload.get("path") or ""),
                "artifact_path": str(payload.get("artifact_path") or "analysis-report.md"),
            }
            source_kind = str(payload.get("source_kind") or "").strip()
            if source_kind:
                request_input["source_kind"] = source_kind
            requested_outputs = payload.get("requested_outputs")
            if isinstance(requested_outputs, list):
                request_input["requested_outputs"] = [
                    str(item or "").strip()
                    for item in requested_outputs
                    if str(item or "").strip()
                ]
            artifact_manifest = payload.get("artifact_manifest")
            if isinstance(artifact_manifest, list):
                request_input["artifact_manifest"] = [
                    dict(item)
                    for item in artifact_manifest
                    if isinstance(item, Mapping)
                ]
            artifact_paths = payload.get("artifact_paths")
            if isinstance(artifact_paths, list):
                request_input["artifact_paths"] = [
                    str(path or "").strip()
                    for path in artifact_paths
                    if str(path or "").strip()
                ]
            if payload.get("max_rows"):
                request_input["max_rows"] = int(payload.get("max_rows") or 1000)
            analyze_request = _request(
                "data.analyze",
                request_input,
                planning_reason="planner_builtin_data_analysis",
            )
            if _data_analysis_requires_model_followup(decision):
                analyze_request["continue_to_model"] = True
                return [
                    *app_requests,
                    *file_open_requests,
                    analyze_request,
                ]
            return [
                *app_requests,
                *file_open_requests,
                analyze_request,
                *_artifact_reveal_tool_requests(
                    decision,
                    allowed,
                    planning_reason="planner_builtin_data_analysis",
                ),
            ]

    inputs = decision.selected_intent.inputs
    context_source = str(inputs.get("context_source") or "").strip()
    if context_source in {"selection", "clipboard"}:
        context_requests = _context_source_tool_requests(
            decision,
            allowed,
            step_ids=("copy-selected-data-context", "read-data-context"),
            planning_reason="planner_prefetch_data_source",
        )
        return _append_model_followup_requests(context_requests, app_requests)
    if context_source in {"current_page_content", "visible_text"}:
        context_requests = _context_source_tool_requests(
            decision,
            allowed,
            step_ids=(
                "select-current-data-context",
                "copy-current-data-context",
                "read-data-context",
            ),
            planning_reason="planner_prefetch_data_source",
        )
        if _data_analysis_opens_spreadsheet_before_context(decision):
            if context_requests:
                return [*app_requests, *file_open_requests, *context_requests]
            return _mark_last_request_for_model_followup([*app_requests, *file_open_requests])
        return _append_model_followup_requests(context_requests, [*app_requests, *file_open_requests])
    source_hint = str(inputs.get("data_source_hint") or "").strip()
    readable_tool = _first_allowed(("workspace.read", "fs.read_file", "file.read"), allowed)
    if _workspace_readable_data_source(source_hint, inputs) and readable_tool:
        request = _request(
            readable_tool,
            {"path": source_hint},
            planning_reason="planner_prefetch_data_source",
        )
        request["continue_to_model"] = True
        return _append_model_followup_requests([request], [*app_requests, *file_open_requests])
    if source_hint:
        return _mark_last_request_for_model_followup([*app_requests, *file_open_requests])
    source_scope = str(inputs.get("data_source_scope_hint") or "").strip()
    if source_scope and not _workspace_listable_data_scope(source_scope):
        return _mark_last_request_for_model_followup([*app_requests, *file_open_requests])
    context_requests = _context_prefetch_tool_requests(
        decision,
        allowed,
        step_ids=("inspect-data-source",),
        planning_reason="planner_prefetch_data_source",
    )
    return _append_model_followup_requests(context_requests, [*app_requests, *file_open_requests])


def _data_analysis_requires_model_followup(decision: Any) -> bool:
    inputs = getattr(getattr(decision, "selected_intent", None), "inputs", None)
    if isinstance(inputs, Mapping):
        target_app = str(inputs.get("target_app_hint") or "").strip()
        target_action = str(inputs.get("target_action_hint") or "").strip()
        if target_app and target_action == "app_paste":
            return True
    followup_step_ids = {
        "prepare-analysis-target-app",
        "draft-analysis-communication",
        "draft-analysis-communication-message",
        "send-analysis-communication-message",
    }
    return any(
        str(getattr(step, "step_id", "") or "").strip() in followup_step_ids
        for step in decision.plan.tool_plan.steps
    )


def _data_analysis_opens_spreadsheet_before_context(decision: Any) -> bool:
    step_ids = [
        str(getattr(step, "step_id", "") or "").strip()
        for step in getattr(getattr(decision, "plan", None), "tool_plan", None).steps
    ]
    try:
        return step_ids.index("open-spreadsheet-app") < step_ids.index("read-data-context")
    except (AttributeError, ValueError):
        return False


def _data_analysis_spreadsheet_app_requests(
    decision: Any,
    allowed: set[str],
) -> list[dict[str, Any]]:
    step = next(
        (
            item
            for item in decision.plan.tool_plan.steps
            if getattr(item, "step_id", "") == "open-spreadsheet-app"
        ),
        None,
    )
    tool_name = str(getattr(step, "tool_name", "") or "").strip()
    if not _step_available(step):
        return []
    if not tool_name or tool_name not in allowed:
        return []
    input_preview = getattr(step, "input_preview", None)
    payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
    return [
        _request(
            tool_name,
            _desktop_request_payload(tool_name, payload),
            planning_reason="planner_fallback_data_analysis_spreadsheet_app",
        )
    ]


def _data_analysis_file_open_requests(
    decision: Any,
    allowed: set[str],
) -> list[dict[str, Any]]:
    step = next(
        (
            item
            for item in decision.plan.tool_plan.steps
            if getattr(item, "step_id", "") == "open-data-file"
        ),
        None,
    )
    tool_name = str(getattr(step, "tool_name", "") or "").strip()
    if not _step_available(step):
        return []
    if tool_name != "desktop.open_path" or tool_name not in allowed:
        return []
    input_preview = getattr(step, "input_preview", None)
    payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
    path = str(payload.get("path") or "").strip()
    if not path:
        return []
    return [
        _request(
            "desktop.open_path",
            {"path": path},
            planning_reason="planner_fallback_data_analysis_file_open",
        )
    ]


def _artifact_reveal_tool_requests(
    decision: Any,
    allowed: set[str],
    *,
    planning_reason: str,
) -> list[dict[str, Any]]:
    step = next(
        (
            item
            for item in decision.plan.tool_plan.steps
            if getattr(item, "step_id", "") == "reveal-artifact-in-finder"
        ),
        None,
    )
    tool_name = str(getattr(step, "tool_name", "") or "").strip()
    if not _step_available(step):
        return []
    if tool_name != "desktop.reveal_path" or tool_name not in allowed:
        return []
    input_preview = getattr(step, "input_preview", None)
    payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
    path = str(payload.get("path") or "").strip()
    if not path:
        return []
    return [
        _request(
            "desktop.reveal_path",
            {"path": path},
            planning_reason=planning_reason,
        )
    ]


def _append_model_followup_requests(
    base_requests: list[dict[str, Any]],
    extra_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not extra_requests:
        return base_requests
    if not base_requests:
        return _mark_last_request_for_model_followup(extra_requests)
    continue_to_model = bool(base_requests[-1].pop("continue_to_model", False))
    requests = [*base_requests, *extra_requests]
    if continue_to_model:
        requests[-1]["continue_to_model"] = True
    return requests


def _mark_last_request_for_model_followup(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if requests:
        requests[-1]["continue_to_model"] = True
    return requests


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
        requests = [
            _request(
                tool_name,
                payload,
                planning_reason="planner_fallback_media_playback",
            )
            for tool_name, payload in app_query_plan
        ]
        if _media_app_query_plan_needs_model_followup(app_query_plan):
            requests[-1]["continue_to_model"] = True
        return requests
    tool_name, payload = media_tool_preview(inputs, allowed)
    if not tool_name:
        return []
    requests = [
        _request(
            tool_name,
            payload,
            planning_reason="planner_fallback_media_playback",
        )
    ]
    verify_request = _media_playback_verify_request(inputs, allowed)
    if verify_request:
        requests.append(verify_request)
    return requests


def _media_app_query_plan_needs_model_followup(
    app_query_plan: list[tuple[str, dict[str, Any]]],
) -> bool:
    has_observation = any(
        tool_name in {"desktop.ui_elements", "desktop.active_window", "screen.capture"}
        for tool_name, _payload in app_query_plan
    )
    has_play_step = any(
        str(tool_name or "").startswith("media.")
        for tool_name, _payload in app_query_plan
    )
    return has_observation and not has_play_step


def _media_playback_verify_request(inputs: Mapping[str, Any], allowed: set[str]) -> dict[str, Any]:
    action = str(inputs.get("action") or "").strip() or "play"
    if action == "status":
        return {}
    tool_name = _first_allowed(("desktop.ui_elements", "desktop.active_window", "screen.capture"), allowed)
    if not tool_name:
        return {}
    payload: dict[str, Any] = {}
    if tool_name == "desktop.ui_elements":
        payload = {"role_filter": "", "limit": 80}
    elif tool_name == "screen.capture":
        payload = {"reason": "verify media playback"}
    return _request(
        tool_name,
        payload,
        planning_reason="planner_fallback_media_playback",
    )


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
    send_action = str(direct_hint.get("send_action") or "send").strip() or "send"
    if _direct_communication_requires_model_body(direct_hint):
        return []
    steps_by_id = {
        str(getattr(step, "step_id", "") or "").strip(): step
        for step in decision.plan.tool_plan.steps
    }
    if body_source in {"selection", "current_page_link"}:
        required_step_ids = ("copy-communication-body-source",)
    else:
        required_step_ids = ()
    if "open-or-focus-app" in steps_by_id:
        required_step_ids += ("open-or-focus-app",)
    required_step_ids += (
        "focus-communication-recipient-search",
        "type-communication-recipient",
        "submit-communication-recipient-search",
    )
    if body_source in {"clipboard", "selection", "current_page_link"}:
        required_step_ids += ("paste-communication-message",)
    else:
        required_step_ids += ("draft-communication-message",)
    if send_action != "draft":
        required_step_ids += (
            "send-communication-message",
        )
    requests: list[dict[str, Any]] = []
    for step_id in required_step_ids:
        step = steps_by_id.get(step_id)
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        if not _step_available(step):
            return []
        if not tool_name or tool_name not in allowed:
            return []
        input_preview = getattr(step, "input_preview", None)
        payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        direct_mode = str(direct_hint.get("mode") or "").strip()
        if (
            step_id == "open-or-focus-app"
            and tool_name == "app.open"
            and "app.focus" in allowed
            and direct_mode == "open"
        ):
            requests.append(
                _request(
                    "app.open",
                    _desktop_request_payload("app.open", payload),
                    planning_reason="planner_fallback_communication_send",
                )
            )
            requests.append(
                _request(
                    "app.focus",
                    _desktop_request_payload("app.focus", payload),
                    planning_reason="planner_fallback_communication_send",
                )
            )
            continue
        if step_id == "open-or-focus-app" and tool_name == "app.open" and "app.focus" in allowed:
            tool_name = "app.focus"
        requests.append(
            _request(
                tool_name,
                _desktop_request_payload(tool_name, payload),
                planning_reason="planner_fallback_communication_send",
            )
        )
    return requests


def _direct_communication_requires_model_body(direct_hint: Mapping[str, Any]) -> bool:
    body_source = str(direct_hint.get("body_source") or "").strip()
    transform = str(direct_hint.get("content_transform_hint") or "").strip()
    if transform and body_source:
        return True
    return body_source in {
        "app_search_result",
        "screen_capture",
        "current_page_content",
        "visible_text",
        "file",
    }


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

    if source == "app_search_result":
        return _direct_app_search_result_context_tool_requests(
            decision,
            allowed,
            planning_reason=planning_reason,
        )

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

    if source == "screen_capture":
        if "screen.capture" not in allowed:
            return []
        request = _request(
            "screen.capture",
            {"reason": "Capture the screen before sending it."},
            planning_reason=planning_reason,
        )
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


def _direct_app_search_result_context_tool_requests(
    decision: Any,
    allowed: set[str],
    *,
    planning_reason: str,
) -> list[dict[str, Any]]:
    source_step_ids = {
        "discover-app-search-source",
        "open-app-search-source",
        "focus-app-search-source",
        "focus-app-search-field",
        "type-app-search-query",
        "submit-app-search",
        "read-communication-context",
    }
    requests: list[dict[str, Any]] = []
    tool_plan = getattr(getattr(decision, "plan", None), "tool_plan", None)
    for step in getattr(tool_plan, "steps", []):
        step_id = str(getattr(step, "step_id", "") or "").strip()
        if step_id not in source_step_ids:
            continue
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        if not tool_name or tool_name not in allowed:
            return []
        input_preview = getattr(step, "input_preview", None)
        payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        request = _request(
            tool_name,
            _desktop_request_payload(tool_name, payload),
            planning_reason=planning_reason,
        )
        if step_id == "read-communication-context":
            request["continue_to_model"] = True
        requests.append(request)
        if step_id == "read-communication-context":
            break
    return requests


def _web_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    browser_action = str(decision.selected_intent.inputs.get("browser_action") or "").strip()
    prepare_requests = _web_browser_prepare_requests(decision, allowed)
    if browser_action == "find_current_page":
        return _current_page_find_tool_requests(decision, allowed)
    if browser_action == "click":
        if "browser.click" not in allowed:
            fallback_requests = _browser_click_desktop_fallback_requests(decision, allowed)
            if fallback_requests:
                return fallback_requests
            return []
        url = str(decision.selected_intent.inputs.get("url_hint") or "").strip()
        if url and "browser.open_url" not in allowed:
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
        requests = [*prepare_requests]
        if url:
            requests.append(
                _request(
                    "browser.open_url",
                    {"url": url},
                    planning_reason="planner_fallback_web_research",
                )
            )
        requests.append(
            _request(
                "browser.click",
                payload,
                planning_reason="planner_fallback_web_research",
            )
        )
        return requests
    if browser_action == "type_text":
        if "browser.type_text" not in allowed:
            return []
        selector = str(decision.selected_intent.inputs.get("selector") or "").strip()
        text = str(decision.selected_intent.inputs.get("text") or "")
        if not selector or not text:
            return []
        payload: dict[str, Any] = {"selector": selector, "text": text}
        for key in ("fallback_x", "fallback_y"):
            value = decision.selected_intent.inputs.get(key)
            if value not in (None, ""):
                payload[key] = value
        return [
            *prepare_requests,
            _request(
                "browser.type_text",
                payload,
                planning_reason="planner_fallback_web_research",
            )
        ]
    if (
        browser_action == "open_search"
        and str(decision.selected_intent.inputs.get("followup_action") or "").strip()
        == "click_search_result"
    ):
        if "browser.open_url" not in allowed or "browser.click" not in allowed:
            return []
        url = str(decision.selected_intent.inputs.get("url_hint") or "").strip()
        selector = str(decision.selected_intent.inputs.get("selector") or "").strip()
        if not url or not selector:
            return []
        click_payload: dict[str, Any] = {"selector": selector}
        click_count = decision.selected_intent.inputs.get("click_count")
        if click_count not in (None, ""):
            click_payload["click_count"] = click_count
        requests = [
            *prepare_requests,
            _request(
                "browser.open_url",
                {"url": url},
                planning_reason="planner_fallback_web_research",
            ),
            _request(
                "browser.click",
                click_payload,
                planning_reason="planner_fallback_web_research",
            ),
        ]
        if (
            str(decision.selected_intent.inputs.get("post_followup_action") or "").strip()
            == "extract_text"
        ):
            post_step = next(
                (
                    item
                    for item in decision.plan.tool_plan.steps
                    if getattr(item, "step_id", "") == "extract-clicked-web-result-text"
                ),
                None,
            )
            post_tool_name = str(getattr(post_step, "tool_name", "") or "").strip()
            if (
                post_tool_name in {"browser.extract_text", "browser.current_page"}
                and post_tool_name in allowed
                and _step_available(post_step)
            ):
                post_request = _request(
                    post_tool_name,
                    {},
                    planning_reason="planner_fallback_web_research",
                )
                presentation = str(
                    decision.selected_intent.inputs.get("presentation") or ""
                ).strip()
                if presentation:
                    post_request["presentation"] = presentation
                if _web_request_needs_model_followup(
                    decision.selected_intent.user_goal
                ) or any(
                    str(getattr(item, "tool_name", "") or "").strip()
                    in {"artifact.write", "clipboard.write"}
                    for item in decision.plan.tool_plan.steps
                ):
                    post_request["continue_to_model"] = True
                requests.append(post_request)
        return requests
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
    url = str(decision.selected_intent.inputs.get("url_hint") or "").strip()
    if browser_action in {"current_page", "extract_text", "screenshot"} and url:
        read_step = next(
            (
                item
                for item in decision.plan.tool_plan.steps
                if getattr(item, "step_id", "")
                in {"read-current-page", "extract-current-page-text", "capture-current-page"}
            ),
            None,
        )
        read_tool_name = str(getattr(read_step, "tool_name", "") or "").strip()
        if (
            "browser.open_url" not in allowed
            or read_tool_name not in allowed
            or not _step_available(read_step)
        ):
            return []
        requests = [
            _request(
                "browser.open_url",
                {"url": url},
                planning_reason="planner_fallback_web_research",
            )
        ]
        payload: dict[str, Any] = {}
        if read_tool_name == "browser.screenshot":
            reason = str(decision.selected_intent.inputs.get("reason") or "").strip()
            payload = {"reason": reason} if reason else {}
        request = _request(
            read_tool_name,
            payload,
            planning_reason="planner_fallback_web_research",
        )
        presentation = str(decision.selected_intent.inputs.get("presentation") or "").strip()
        if presentation:
            request["presentation"] = presentation
        if _web_read_request_needs_model_followup(decision, read_tool_name, presentation):
            request["continue_to_model"] = True
        requests.append(request)
        return [*prepare_requests, *requests]
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
    if not _step_available(step):
        return []
    if tool_name not in allowed:
        return []
    payload: dict[str, Any] = {}
    if tool_name == "browser.search":
        query = str(decision.selected_intent.inputs.get("query") or "").strip()
        if not query:
            return []
        payload = {"query": query}
    elif tool_name in {
        "browser.open_url",
        "browser.open",
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
    elif tool_name not in {
        "browser.current_page",
        "browser.extract_text",
        "browser.extract",
        "browser.screenshot",
    }:
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
    if _web_read_request_needs_model_followup(decision, tool_name, presentation) and (
        not browser_action
        or _browser_tool_result_can_feed_model(tool_name)
        or any(
            str(getattr(item, "tool_name", "") or "").strip()
            in {"artifact.write", "clipboard.write"}
            for item in decision.plan.tool_plan.steps
        )
    ):
        request["continue_to_model"] = True
    return [*prepare_requests, request]


def _web_read_request_needs_model_followup(
    decision: Any,
    tool_name: str,
    presentation: str,
) -> bool:
    if _web_read_request_can_direct_present(decision, tool_name, presentation):
        return False
    inputs = decision.selected_intent.inputs
    return bool(
        _web_request_needs_model_followup(decision.selected_intent.user_goal)
        or str(inputs.get("output_target_hint") or "").strip() == "clipboard"
        or str(presentation or "").strip()
    )


def _web_read_request_can_direct_present(
    decision: Any,
    tool_name: str,
    presentation: str,
) -> bool:
    if str(presentation or "").strip() != "summary":
        return False
    if tool_name not in {
        "browser.current_page",
        "browser.extract_text",
        "browser.extract",
        "browser.open_url_and_extract_text",
    }:
        return False
    inputs = decision.selected_intent.inputs
    if str(inputs.get("output_target_hint") or "").strip():
        return False
    return not any(
        str(getattr(item, "tool_name", "") or "").strip()
        in {"artifact.write", "clipboard.write"}
        for item in decision.plan.tool_plan.steps
    )


def _browser_tool_result_can_feed_model(tool_name: str) -> bool:
    return tool_name in {
        "browser.current_page",
        "browser.extract_text",
        "browser.extract",
        "browser.screenshot",
        "browser.search",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
    }


def _web_browser_prepare_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    inputs = decision.selected_intent.inputs
    app_name = str(inputs.get("app_name") or "").strip()
    if not app_name:
        return []
    mode = str(inputs.get("app_mode") or "focus").strip() or "focus"
    tool_name = _first_allowed(app_control_tool_candidates(mode), allowed)
    if not tool_name:
        return []
    return [
        _request(
            tool_name,
            _desktop_request_payload(tool_name, {"app_name": app_name}),
            planning_reason="planner_fallback_web_research",
        )
    ]


def _browser_click_desktop_fallback_requests(
    decision: Any,
    allowed: set[str],
) -> list[dict[str, Any]]:
    inputs = decision.selected_intent.inputs
    app_name = str(inputs.get("app_name") or "").strip()
    selector = str(inputs.get("selector") or "").strip()
    if not app_name or not selector.startswith("text="):
        return []
    target = selector.removeprefix("text=").strip()
    if not target:
        return []
    payload = {
        "app_name": app_name,
        "target": target,
        "role_filter": "button",
        "click_count": int(inputs.get("click_count") or 1),
        "limit": 80,
    }
    app_click_tool = _first_allowed(
        ("app.focus_and_click_ui_element", "app.open_and_click_ui_element"),
        allowed,
    )
    requests: list[dict[str, Any]] = []
    if app_click_tool:
        requests.append(
            _request(
                app_click_tool,
                _desktop_request_payload(app_click_tool, payload),
                planning_reason="planner_desktop_operation",
            )
        )
    elif "app.focus" in allowed and "desktop.click_ui_element" in allowed:
        requests.extend(
            [
                _request(
                    "app.focus",
                    _desktop_request_payload("app.focus", {"app_name": app_name}),
                    planning_reason="planner_desktop_operation",
                ),
                _request(
                    "desktop.click_ui_element",
                    _desktop_request_payload(
                        "desktop.click_ui_element",
                        {
                            "target": target,
                            "role_filter": "button",
                            "click_count": int(inputs.get("click_count") or 1),
                            "limit": 80,
                        },
                    ),
                    planning_reason="planner_desktop_operation",
                ),
            ]
        )
    if requests and "desktop.ui_elements" in allowed:
        requests.append(
            _request(
                "desktop.ui_elements",
                {"role_filter": "button", "limit": 80},
                planning_reason="planner_desktop_operation",
            )
        )
    return requests


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
        if not _step_available(step):
            return []
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
        if not _step_available(step):
            return []
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
    if not _step_available(step):
        return None
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
    if tool_name in {"workspace.list", "fs.find_files", "file.search"}:
        path = str(payload.get("path") or "").strip()
        request_payload: dict[str, Any] = {"path": path} if path else {}
        pattern = str(payload.get("pattern") or "").strip()
        file_type = str(payload.get("file_type") or "").strip()
        if pattern:
            request_payload["pattern"] = pattern
        if file_type:
            request_payload["file_type"] = file_type
        return request_payload
    if tool_name in {"workspace.read", "fs.read_file", "file.read"}:
        path = str(payload.get("path") or "").strip()
        return {"path": path} if path else None
    if tool_name in {"browser.current_page", "browser.extract_text", "browser.screenshot"}:
        return {}
    if tool_name == "clipboard.read":
        return {}
    if tool_name == "desktop.safe_shortcut":
        action = str(payload.get("action") or "").strip()
        return {"action": action} if action else None
    if tool_name in {"desktop.ui_elements", "desktop.read_ui"}:
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


def _direct_schedule_context_app_item_tool_requests(
    decision: Any,
    allowed: set[str],
) -> list[dict[str, Any]]:
    source = str(decision.selected_intent.inputs.get("context_source") or "").strip()
    if source not in {"selection", "clipboard", "current_page_link", "current_page_content"}:
        return []
    app_name, shortcut_action = _schedule_context_app_item_target(
        str(decision.selected_intent.user_goal or "")
    )
    if not app_name or not shortcut_action:
        return []
    app_tool = _first_allowed(("app.open",), allowed)
    shortcut_tool = _first_allowed(("desktop.safe_shortcut",), allowed)
    app_shortcut_tool = _first_allowed(("app.open_and_safe_shortcut",), allowed)
    if not shortcut_tool or not (app_tool or app_shortcut_tool):
        return []
    planning_reason = "planner_fallback_schedule_context_app_item"
    source_requests = _direct_context_clipboard_copy_requests(
        source,
        allowed,
        planning_reason=planning_reason,
    )
    if source_requests is None:
        return []
    if app_tool:
        return [
            *source_requests,
            _request(
                app_tool,
                {"app_name": app_name},
                planning_reason=planning_reason,
            ),
            _request(
                shortcut_tool,
                {"action": shortcut_action},
                planning_reason=planning_reason,
            ),
            _request(
                shortcut_tool,
                {"action": "paste"},
                planning_reason=planning_reason,
            ),
        ]
    return [
        *source_requests,
        _request(
            app_shortcut_tool,
            {"app_name": app_name, "action": shortcut_action},
            planning_reason=planning_reason,
        ),
        _request(
            shortcut_tool,
            {"action": "paste"},
            planning_reason=planning_reason,
        ),
    ]


def _schedule_context_app_item_target(text: str) -> tuple[str, str]:
    lowered = str(text or "").lower()
    if any(term in lowered for term in ("calendar", "日历", "日程", "事件", "event")):
        return "Calendar", "new_event"
    if any(term in lowered for term in ("reminder", "reminders", "提醒", "提醒事项")):
        return "Reminders", "new_reminder"
    return "", ""


def _direct_context_clipboard_copy_requests(
    source: str,
    allowed: set[str],
    *,
    planning_reason: str,
) -> list[dict[str, Any]] | None:
    if source == "clipboard":
        return []
    if "desktop.safe_shortcut" not in allowed:
        return None
    if source == "selection":
        return [
            _request(
                "desktop.safe_shortcut",
                {"action": "copy"},
                planning_reason=planning_reason,
            )
        ]
    if source == "current_page_link":
        return [
            _request(
                "desktop.safe_shortcut",
                {"action": "copy_current_page_link"},
                planning_reason=planning_reason,
            )
        ]
    if source == "current_page_content":
        return [
            _request(
                "desktop.safe_shortcut",
                {"action": "select_all"},
                planning_reason=planning_reason,
            ),
            _request(
                "desktop.safe_shortcut",
                {"action": "copy"},
                planning_reason=planning_reason,
            ),
        ]
    return None


def _information_capture_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    artifact_request = _information_capture_artifact_request(decision, allowed)
    if artifact_request:
        return [artifact_request]
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


def _information_capture_artifact_request(
    decision: Any,
    allowed: set[str],
) -> dict[str, Any] | None:
    step = next(
        (
            item
            for item in decision.plan.tool_plan.steps
            if getattr(item, "step_id", "") == "write-note-artifact"
        ),
        None,
    )
    tool_name = str(getattr(step, "tool_name", "") or "").strip()
    if not _step_available(step):
        return None
    if tool_name != "artifact.write" or tool_name not in allowed:
        return None
    input_preview = getattr(step, "input_preview", None)
    payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
    if not str(payload.get("path") or "").strip() or not str(payload.get("content") or "").strip():
        return None
    return _request(
        tool_name,
        {
            "path": str(payload.get("path") or ""),
            "content": str(payload.get("content") or ""),
        },
        planning_reason="planner_fallback_information_capture",
    )


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
            "摘要",
            "输出",
            "最像",
            "最接近",
            "相关",
            "有关",
            "匹配",
            "合适",
            "适合",
            "应该",
            "可能",
            "哪个",
            "哪里",
            "哪一个",
            "which",
            "where",
            "closest",
            "similar",
            "related",
            "matching",
            "appropriate",
            "suitable",
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
