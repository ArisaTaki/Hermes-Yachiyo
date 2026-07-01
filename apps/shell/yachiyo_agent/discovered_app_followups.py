"""Shared execution guards for discovered desktop app follow-ups."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def planner_discovered_app_followup_can_direct_execute(
    selection_payload: Mapping[str, Any],
    planned_requests: list[dict[str, Any]],
    allowed_tools: Iterable[str],
    *,
    allow_open_path: bool = False,
    allow_communication_compose: bool = False,
) -> bool:
    if len(planned_requests) != 1:
        return False
    request = planned_requests[0]
    if str(request.get("tool") or "").strip() != "desktop.list_apps":
        return False
    if not bool(request.get("continue_to_model")):
        return False
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    return discovered_app_followup_target_can_direct_execute(
        target,
        allowed_tools,
        allow_open_path=allow_open_path,
        allow_communication_compose=allow_communication_compose,
    )


def discovered_app_followup_target_can_direct_execute(
    target: Mapping[str, Any],
    allowed_tools: Iterable[str],
    *,
    allow_open_path: bool = False,
    allow_communication_compose: bool = False,
) -> bool:
    if str(target.get("kind") or "").strip() != "desktop_discovered_app_action":
        return False
    if isinstance(target.get("creative_canvas"), Mapping):
        return False
    if isinstance(target.get("communication_compose"), Mapping) and not allow_communication_compose:
        return False
    if str(target.get("body_source") or "").strip() == "model_generated_content":
        return False

    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    target_action = str(target.get("target_action") or "").strip()
    if target_action == "safe_shortcut":
        can_prepare = _can_prepare_safe_shortcut(target, allowed)
    elif target_action == "app_search":
        if not _app_search_query(target):
            return False
        can_prepare = _can_prepare_app_search(target, allowed)
        if not can_prepare:
            return False
        if not (
            "desktop.safe_type_text" in allowed
            or "app.focus_and_safe_type_text" in allowed
        ):
            return False
        if _app_search_submit_requested(target) and "desktop.search_submit" not in allowed:
            return False
        if not _can_select_app_search_result(target, allowed):
            return False
    elif target_action in {"open_app", "open", "focus_app", "focus"}:
        can_prepare = _can_prepare_app(target, allowed)
    elif target_action == "open_path_with_selected_app":
        can_prepare = (
            allow_open_path
            and bool(str(target.get("target_path") or "").strip())
            and "desktop.open_path_with_app" in allowed
        )
    else:
        return False
    if not can_prepare:
        return False
    if str(target.get("compose_text") or "").strip() and not (
        "desktop.safe_type_text" in allowed
        or "app.focus_and_safe_type_text" in allowed
    ):
        return False
    return True


def _can_prepare_safe_shortcut(target: Mapping[str, Any], allowed: set[str]) -> bool:
    if not str(target.get("safe_shortcut_action") or "").strip():
        return False
    return (
        "app.open_and_safe_shortcut" in allowed
        or "app.focus_and_safe_shortcut" in allowed
        or (
            _can_prepare_app(target, allowed)
            and "desktop.safe_shortcut" in allowed
        )
    )


def _can_prepare_app(_target: Mapping[str, Any], allowed: set[str]) -> bool:
    return bool(
        allowed
        & {
            "app.open",
            "desktop.open_app",
            "app.focus",
            "desktop.focus_app",
        }
    )


def _can_prepare_app_search(target: Mapping[str, Any], allowed: set[str]) -> bool:
    focus = _app_search_focus(target)
    if str(focus.get("tool") or "").strip() == "desktop.click_ui_element":
        return (
            "desktop.click_ui_element" in allowed
            and _can_prepare_app(target, allowed)
        )
    return _can_prepare_safe_shortcut(target, allowed)


def _app_search_focus(target: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = target.get("app_search") if isinstance(target.get("app_search"), Mapping) else {}
    focus = raw.get("focus") if isinstance(raw.get("focus"), Mapping) else {}
    return focus


def _app_search_query(target: Mapping[str, Any]) -> str:
    raw = target.get("app_search") if isinstance(target.get("app_search"), Mapping) else {}
    return str(raw.get("query") or target.get("app_search_query") or "").strip()


def _app_search_submit_requested(target: Mapping[str, Any]) -> bool:
    raw = target.get("app_search") if isinstance(target.get("app_search"), Mapping) else {}
    result_selection = _app_search_result_selection(target)
    if str(result_selection.get("action") or "").strip() == "key_confirm":
        return False
    if (
        str(raw.get("submit_action") or target.get("app_search_submit_action") or "").strip()
        == "confirm"
    ):
        return False
    submit = raw.get("submit", target.get("app_search_submit"))
    if isinstance(submit, bool):
        return submit
    if str(submit or "").strip().lower() in {"1", "true", "yes", "y"}:
        return True
    return bool(str(raw.get("submit_action") or target.get("app_search_submit_action") or "").strip())


def _can_select_app_search_result(target: Mapping[str, Any], allowed: set[str]) -> bool:
    result_selection = _app_search_result_selection(target)
    action = str(result_selection.get("action") or "").strip()
    if not action:
        return True
    if action == "click":
        tool_name = str(result_selection.get("tool") or "").strip()
        if tool_name:
            return tool_name in allowed
        return (
            "desktop.click_ui_element" in allowed
            or "app.focus_and_click_ui_element" in allowed
        )
    if action == "key_confirm":
        key = result_selection.get("key") if isinstance(result_selection.get("key"), Mapping) else {}
        confirm = (
            result_selection.get("confirm")
            if isinstance(result_selection.get("confirm"), Mapping)
            else {}
        )
        key_tool = str(key.get("tool") or "desktop.safe_key").strip()
        confirm_tool = str(confirm.get("tool") or "desktop.submit_foreground").strip()
        return key_tool in allowed and confirm_tool in allowed
    return False


def _app_search_result_selection(target: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = target.get("app_search") if isinstance(target.get("app_search"), Mapping) else {}
    result_selection = (
        raw.get("result_selection")
        if isinstance(raw.get("result_selection"), Mapping)
        else {}
    )
    if result_selection:
        return result_selection
    if str(raw.get("select_result") or target.get("app_search_select_result") or "").strip() == "arrow_down":
        return {"action": "key_confirm"}
    return {}
