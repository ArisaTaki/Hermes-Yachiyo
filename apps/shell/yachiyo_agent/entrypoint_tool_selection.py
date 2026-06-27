"""Planner-first direct tool selection for lightweight Chat entrypoints."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .planner_execution import planner_direct_decision_and_tool_requests
from .planner_projection import planner_selection_payload
from .terminal_plan_hints import terminal_command_hint

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
    if _should_consult_legacy(prompt, planner_requests):
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


def _should_consult_legacy(prompt: str, requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return True
    tools = _request_tools(requests)
    if _runtime_planner_model_followup_owns_selection(requests):
        return False
    if _runtime_planner_media_playback_owns_selection(requests):
        return False
    if _prompt_contains_foreground_paste(prompt) and "clipboard.read" in _request_tool_set(requests):
        return True
    if _runtime_planner_clipboard_owns_selection(requests):
        return False
    if _runtime_planner_web_research_owns_selection(requests):
        return False
    if _runtime_planner_communication_send_owns_selection(requests):
        return False
    if _runtime_planner_desktop_discovery_owns_selection(requests):
        return False
    if _runtime_planner_safe_shortcut_owns_selection(requests):
        return False
    if _runtime_planner_app_launch_owns_selection(requests, prompt=prompt):
        return False
    if _runtime_planner_desktop_observation_owns_selection(requests):
        return False
    if _runtime_planner_desktop_operation_owns_selection(requests):
        return False
    if _runtime_planner_system_control_owns_selection(requests):
        return False
    if _runtime_planner_file_access_owns_selection(requests):
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
        "planner_prefetch_code_context",
        "planner_prefetch_data_source",
        "planner_prefetch_file_scope",
        "planner_prefetch_report_context",
        "planner_prefetch_information_capture_context",
        "planner_prefetch_schedule_context",
        "planner_prefetch_communication_context",
        "planner_prefetch_communication_surface",
        "planner_prefetch_web_context",
    }
)


def _runtime_planner_model_followup_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    if not any(bool(request.get("continue_to_model")) for request in requests):
        return False
    reasons = _request_planning_reasons(requests)
    return bool(reasons) and reasons <= _RUNTIME_PLANNER_OWNED_MODEL_FOLLOWUP_REASONS


def _runtime_planner_media_playback_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = _request_planning_reasons(requests)
    if reasons != {"planner_fallback_media_playback"}:
        return False
    tools = _request_tool_set(requests)
    return bool(tools) and all(tool.startswith("media.") for tool in tools)


def _runtime_planner_clipboard_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = _request_planning_reasons(requests)
    if reasons != {"planner_fallback_clipboard"}:
        return False
    tools = _request_tool_set(requests)
    return bool(tools & {"clipboard.read", "clipboard.write"}) and tools <= {
        "clipboard.read",
        "clipboard.write",
        "desktop.safe_shortcut",
    }


def _runtime_planner_web_research_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = _request_planning_reasons(requests)
    if reasons != {"planner_fallback_web_research"}:
        return False
    tools = _request_tool_set(requests)
    return bool(tools) and tools <= {
        "browser.current_page",
        "browser.extract_text",
        "browser.open_url",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
        "browser.screenshot",
    }


def _runtime_planner_communication_send_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = _request_planning_reasons(requests)
    return reasons == {"planner_fallback_communication_send"}


def _runtime_planner_desktop_discovery_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = _request_planning_reasons(requests)
    if reasons != {"planner_fallback_desktop_operation"}:
        return False
    tools = _request_tool_set(requests)
    return bool(tools) and tools <= _RUNTIME_PLANNER_DESKTOP_DISCOVERY_TOOLS


def _runtime_planner_safe_shortcut_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = _request_planning_reasons(requests)
    if reasons not in (
        {"planner_fallback_desktop_operation"},
        {"planner_fallback_desktop_hotkey"},
    ):
        return False
    for request in requests:
        if not isinstance(request, Mapping):
            return False
        tool_name = str(request.get("tool") or "").strip()
        if tool_name not in {
            "desktop.safe_shortcut",
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
        }:
            return False
        request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        if tool_name != "desktop.safe_shortcut" and not _runtime_app_name_is_specific(
            str(request_input.get("app_name") or "")
        ):
            return False
        if not str(request_input.get("action") or "").strip():
            return False
    return True


_RUNTIME_PLANNER_DESKTOP_DISCOVERY_TOOLS = frozenset(
    {
        "desktop.active_window",
        "desktop.list_apps",
        "desktop.permissions",
        "desktop.running_apps",
        "desktop.ui_elements",
        "desktop.windows",
        "screen.capture",
    }
)


def _runtime_planner_app_launch_owns_selection(
    requests: list[dict[str, Any]],
    *,
    prompt: str = "",
) -> bool:
    if not requests:
        return False
    if _prompt_contains_terminal_command(prompt):
        return False
    if _prompt_contains_shortcut_or_window_followup(prompt):
        return False
    reasons = _request_planning_reasons(requests)
    if reasons != {"planner_fallback_desktop_operation"}:
        return False
    tools = _request_tool_set(requests)
    if not tools or not tools <= {"app.open", "app.focus"}:
        return False
    for request in requests:
        request_input = request.get("input") if isinstance(request, dict) else {}
        if not isinstance(request_input, Mapping):
            return False
        if not _runtime_app_name_is_specific(str(request_input.get("app_name") or "")):
            return False
    return True


def _prompt_contains_terminal_command(prompt: str) -> bool:
    return bool(terminal_command_hint(prompt))


def _prompt_contains_shortcut_or_window_followup(prompt: str) -> bool:
    value = str(prompt or "").strip()
    lowered = value.lower()
    return bool(
        re.search(
            r"(?:全选|复制|粘贴|撤销|重做|查找|刷新|"
            r"新建标签页|新开(?:一个)?标签页|关闭当前标签页|"
            r"下一个窗口|上一个窗口|下一个标签页|上一个标签页|"
            r"下一个应用|上一个应用|切换到下一个应用|切换到上一个应用|"
            r"最大化|全屏|任务控制中心|当前应用窗口|聚焦搜索|emoji\s*面板|强制退出|"
            r"select\s+all|copy|paste|undo|redo|find|refresh|reload|"
            r"new\s+tab|close\s+tab|next\s+window|previous\s+window|"
            r"next\s+app|previous\s+app|"
            r"next\s+tab|previous\s+tab|mission\s+control|app\s+windows|"
            r"spotlight|emoji\s+picker|force\s+quit)",
            value,
            flags=re.IGNORECASE,
        )
        or bool(re.search(r"\b(?:go\s+)?(?:back|forward)(?:\s+(?:one\s+)?page)?\b", lowered))
    )


def _prompt_contains_foreground_paste(prompt: str) -> bool:
    return bool(
        re.search(
            r"(?:粘贴|paste).*(?:当前|前台|输入框|文本框|输入栏|current|foreground|input|field)",
            str(prompt or ""),
            flags=re.IGNORECASE,
        )
    )


def _runtime_planner_desktop_observation_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = _request_planning_reasons(requests)
    if reasons != {"planner_fallback_desktop_operation"}:
        return False
    tools = _request_tools(requests)
    if len(tools) != 2 or tools[1] not in {"desktop.ui_elements", "screen.capture"}:
        return False
    if tools[0] not in {"app.open", "app.focus", "app.focus_window"}:
        return False
    first_request = requests[0] if isinstance(requests[0], dict) else {}
    first_input = first_request.get("input")
    if not isinstance(first_input, Mapping):
        return False
    app_name = str(first_input.get("app_name") or "").strip()
    return _runtime_app_name_is_specific(app_name)


_RUNTIME_PLANNER_DESKTOP_OPERATION_TOOLS = frozenset(
    {
        "app.open",
        "app.focus",
        "app.focus_window",
        "app.status",
        "app.show",
        "app.hide",
        "app.minimize",
        "app.quit",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "app.open_and_safe_key",
        "app.focus_and_safe_key",
        "app.open_and_safe_scroll",
        "app.focus_and_safe_scroll",
        "app.open_and_safe_click",
        "app.focus_and_safe_click",
        "app.open_and_safe_type_text",
        "app.focus_and_safe_type_text",
        "app.open_and_hotkey",
        "app.focus_and_hotkey",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.safe_shortcut",
        "desktop.safe_key",
        "desktop.safe_scroll",
        "desktop.safe_click",
        "desktop.safe_type_text",
        "desktop.hotkey",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.search_submit",
        "desktop.submit_foreground",
    }
)


def _runtime_planner_desktop_operation_owns_selection(
    requests: list[dict[str, Any]],
) -> bool:
    if not requests:
        return False
    if any(bool(request.get("continue_to_model")) for request in requests):
        return False
    reasons = _request_planning_reasons(requests)
    if reasons not in (
        {"planner_fallback_desktop_operation"},
        {"planner_fallback_desktop_hotkey"},
    ):
        return False
    tools = _request_tool_set(requests)
    if not tools or not tools <= _RUNTIME_PLANNER_DESKTOP_OPERATION_TOOLS:
        return False
    return all(_runtime_planner_desktop_request_is_complete(request) for request in requests)


def _runtime_planner_desktop_request_is_complete(request: dict[str, Any]) -> bool:
    tool_name = str(request.get("tool") or "").strip()
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    if tool_name.startswith("app.") and not _runtime_app_name_is_specific(
        str(request_input.get("app_name") or "")
    ):
        return False
    if tool_name in {"app.open", "app.focus", "app.focus_window"}:
        return True
    if tool_name in {"app.status", "app.show", "app.hide", "app.minimize", "app.quit"}:
        return True
    if tool_name in {"desktop.search_submit"}:
        return True
    if tool_name == "desktop.submit_foreground":
        return _has_text_input(request_input, "action")
    if tool_name.endswith("safe_shortcut") or tool_name == "desktop.safe_shortcut":
        return _has_text_input(request_input, "action")
    if tool_name.endswith("safe_key") or tool_name == "desktop.safe_key":
        return _has_text_input(request_input, "action")
    if tool_name.endswith("safe_scroll") or tool_name == "desktop.safe_scroll":
        return _has_text_input(request_input, "direction")
    if tool_name.endswith("safe_click") or tool_name == "desktop.safe_click":
        return _has_numeric_input(request_input, "x") and _has_numeric_input(request_input, "y")
    if tool_name.endswith("safe_type_text") or tool_name == "desktop.safe_type_text":
        return _has_text_input(request_input, "text")
    if tool_name.endswith("hotkey") or tool_name == "desktop.hotkey":
        return _has_text_input(request_input, "key")
    if tool_name.endswith("click_ui_element") or tool_name == "desktop.click_ui_element":
        return _has_text_input(request_input, "target")
    if tool_name.endswith("type_into_ui_element") or tool_name == "desktop.type_into_ui_element":
        return _has_text_input(request_input, "target") and _has_text_input(request_input, "text")
    return False


def _has_text_input(payload: Mapping[str, Any], key: str) -> bool:
    return bool(str(payload.get(key) or "").strip())


def _has_numeric_input(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def _runtime_app_name_is_specific(app_name: str) -> bool:
    if not app_name:
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


_RUNTIME_PLANNER_SYSTEM_CONTROL_TOOLS = frozenset(
    {
        "system.settings_open",
        "system.volume",
        "system.brightness",
        "system.display_sleep",
        "system.screen_saver_start",
    }
)


def _runtime_planner_system_control_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = _request_planning_reasons(requests)
    if reasons != {"planner_fallback_system_control"}:
        return False
    tool_set = _request_tool_set(requests)
    return bool(tool_set & _RUNTIME_PLANNER_SYSTEM_CONTROL_TOOLS) and tool_set <= (
        _RUNTIME_PLANNER_SYSTEM_CONTROL_TOOLS | {"desktop.ui_elements"}
    )


def _runtime_planner_file_access_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = _request_planning_reasons(requests)
    if reasons != {"planner_fallback_file_access"}:
        return False
    tools = _request_tool_set(requests)
    return bool(tools) and tools <= {"desktop.open_path", "desktop.reveal_path"}


def _request_tools(requests: list[dict[str, Any]]) -> list[str]:
    return [
        str(request.get("tool") or "").strip()
        for request in requests
        if isinstance(request, dict)
    ]


def _request_tool_set(requests: list[dict[str, Any]]) -> set[str]:
    return {tool for tool in _request_tools(requests) if tool}


def _request_planning_reasons(requests: list[dict[str, Any]]) -> set[str]:
    return {
        str(request.get("planning_reason") or "").strip()
        for request in requests
        if isinstance(request, dict)
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
