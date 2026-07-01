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
        can_prepare = _can_prepare_safe_shortcut(target, allowed)
        if not can_prepare:
            return False
        if not (
            "desktop.safe_type_text" in allowed
            or "app.focus_and_safe_type_text" in allowed
        ):
            return False
        if _app_search_submit_requested(target) and "desktop.search_submit" not in allowed:
            return False
    elif target_action in {"open_app", "open", "focus_app", "focus"}:
        can_prepare = "app.open" in allowed or "app.focus" in allowed
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
            ("app.open" in allowed or "app.focus" in allowed)
            and "desktop.safe_shortcut" in allowed
        )
    )


def _app_search_query(target: Mapping[str, Any]) -> str:
    raw = target.get("app_search") if isinstance(target.get("app_search"), Mapping) else {}
    return str(raw.get("query") or target.get("app_search_query") or "").strip()


def _app_search_submit_requested(target: Mapping[str, Any]) -> bool:
    raw = target.get("app_search") if isinstance(target.get("app_search"), Mapping) else {}
    submit = raw.get("submit", target.get("app_search_submit"))
    if isinstance(submit, bool):
        return submit
    if str(submit or "").strip().lower() in {"1", "true", "yes", "y"}:
        return True
    return bool(str(raw.get("submit_action") or target.get("app_search_submit_action") or "").strip())
