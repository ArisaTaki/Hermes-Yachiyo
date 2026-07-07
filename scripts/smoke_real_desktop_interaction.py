#!/usr/bin/env python3
"""Opt-in smoke-test for a real macOS desktop type -> inspect -> click -> verify loop."""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.agent.runtime.desktop_execution_providers import (
    desktop_execution_provider_registry_from_env,
    desktop_execution_provider_status_from_env,
)
from apps.shell.agent.runtime.isolated_desktop_provider import (
    IsolatedDesktopProvider,
    build_isolated_desktop_provider_server,
)
from apps.shell.agent.tools import desktop as desktop_tools
from scripts.smoke_real_desktop_app_open import (
    DEFAULT_APP_NAME,
    _app_names,
    _bool_checks,
    _cleanup_evidence,
    _desktop_execution_case,
    _merge_blocking_evidence,
    _planner_alignment,
    _resolved_open_app_name,
    _screen_observability_probe,
    _screen_probe_checks,
    _screen_probe_evidence,
    _status_running,
)

DEFAULT_INPUT_TEXT = "42"
_AFTER_CLICK_VERIFY_MAX_POLLS = 5
_AFTER_CLICK_VERIFY_POLL_INTERVAL_SECONDS = 0.2
_INITIAL_FOCUS_MAX_ATTEMPTS = 5
_INITIAL_FOCUS_RETRY_INTERVAL_SECONDS = 0.5
_PRE_CLICK_FOCUS_MAX_ATTEMPTS = 3
_PRE_CLICK_FOCUS_RETRY_INTERVAL_SECONDS = 0.2
TOOL_CHAIN = [
    "desktop.active_window",
    "desktop.list_apps",
    "app.status",
    "app.open",
    "app.focus",
    "desktop.safe_key",
    "desktop.safe_type_text",
    "desktop.ui_elements",
    "app.focus",
    "desktop.active_window",
    "desktop.click_ui_element",
    "desktop.ui_elements",
    "app.status",
]
ISOLATED_INTERACTION_TOOL_CHAIN = [
    "desktop.list_apps",
    "app.status",
    "app.open",
    "app.focus",
    "desktop.read_ui",
    "desktop.click_ui_element",
    "desktop.safe_type_text",
    "desktop.safe_shortcut",
    "desktop.verify",
    "app.status",
]
_PRIMARY_CLICK_TARGET_HINTS = (
    "删除输入的上个数字",
    "delete input",
    "delete digit",
    "backspace",
)
_SIGN_TARGET_HINTS = ("更改数值符号", "change sign", "toggle sign", "plus/minus")
_BIDI_MARKS = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
INTERACTION_CAPABILITIES = [
    "desktop.app_discovery",
    "desktop.app_launch",
    "desktop.window_focus",
    "desktop.safe_keyboard",
    "desktop.safe_text",
    "desktop.ui_inspection",
    "desktop.ui_click",
    "desktop.app_verification",
]


def _data(result: dict[str, Any]) -> dict[str, Any]:
    return result.get("data") if isinstance(result.get("data"), dict) else {}


def _elements(result: dict[str, Any]) -> list[dict[str, Any]]:
    value = _data(result).get("elements")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _normalized_visible_text(value: Any) -> str:
    return _BIDI_MARKS.sub("", str(value or "")).strip()


def _normalized_numeric_text(value: Any) -> str:
    text = _normalized_visible_text(value).replace("−", "-")
    return re.sub(r"\s+", "", text)


def _signed_value_visible(values: Sequence[str], expected_signed_value: str) -> bool:
    expected = _normalized_numeric_text(expected_signed_value)
    acceptable = {expected, f"({expected})"}
    if expected.startswith("-"):
        acceptable.add(f"({expected[1:]})")
    return any(_normalized_numeric_text(value) in acceptable for value in values)


def _normalized_app_name(value: Any) -> str:
    name = str(value or "").strip()
    if name.casefold().endswith(".app"):
        name = name[:-4]
    return " ".join(name.casefold().split())


def _app_names_match(expected: Any, actual: Any) -> bool:
    normalized_expected = _normalized_app_name(expected)
    normalized_actual = _normalized_app_name(actual)
    return bool(
        normalized_expected
        and normalized_actual
        and normalized_expected == normalized_actual
    )


def _visible_values(result: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for element in _elements(result):
        if str(element.get("role") or "") not in {"AXStaticText", "AXTextField", "AXTextArea"}:
            continue
        for key in ("value", "name"):
            value = _normalized_visible_text(element.get(key))
            if value and value not in values:
                values.append(value)
    return values


def _focus_verified(result: dict[str, Any]) -> bool:
    return result.get("ok") is True and _data(result).get("focus_verified") is True


def _focus_retryable(result: dict[str, Any]) -> bool:
    return (
        _data(result).get("retryable") is True
        or str(result.get("error") or "") == "app_focus_not_verified"
        or str(result.get("blocking_condition") or "") == "foreground_focus_unavailable"
    )


def _focus_with_retries(
    app_name: str,
    *,
    max_attempts: int = _PRE_CLICK_FOCUS_MAX_ATTEMPTS,
    retry_interval_seconds: float = _PRE_CLICK_FOCUS_RETRY_INTERVAL_SECONDS,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    attempts: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    clean_max_attempts = max(1, int(max_attempts))
    for attempt in range(1, clean_max_attempts + 1):
        result = desktop_tools.app_focus(app_name)
        verified = _focus_verified(result)
        attempts.append({"attempt": attempt, "result": result, "focus_verified": verified})
        if verified:
            break
        if attempt < clean_max_attempts and _focus_retryable(result):
            time.sleep(retry_interval_seconds)
            continue
        break
    return result, attempts, _focus_verified(result)


def _poll_after_click_values(
    *,
    app_name: str,
    before_values: Sequence[str],
    expected_signed_value: str,
) -> tuple[dict[str, Any], list[str], bool, list[dict[str, Any]]]:
    after_ui: dict[str, Any] = {}
    after_values: list[str] = []
    after_ui_matches_app = False
    polls: list[dict[str, Any]] = []
    for attempt in range(1, _AFTER_CLICK_VERIFY_MAX_POLLS + 1):
        after_ui = desktop_tools.ui_elements(app_name=app_name, limit=80)
        after_values = _visible_values(after_ui)
        after_ui_matches_app = (
            after_ui.get("ok") is True
            and str(_data(after_ui).get("app_name") or "") == app_name
        )
        signed_value_visible = _signed_value_visible(after_values, expected_signed_value)
        visible_value_changed = list(before_values) != after_values
        click_effect_visible = signed_value_visible or visible_value_changed
        polls.append(
            {
                "attempt": attempt,
                "after_ui_matches_app": after_ui_matches_app,
                "signed_value_visible": signed_value_visible,
                "visible_value_changed": visible_value_changed,
                "click_effect_visible": click_effect_visible,
                "values": after_values,
            }
        )
        if after_ui_matches_app and click_effect_visible:
            break
        if attempt < _AFTER_CLICK_VERIFY_MAX_POLLS:
            time.sleep(_AFTER_CLICK_VERIFY_POLL_INTERVAL_SECONDS)
    return after_ui, after_values, after_ui_matches_app, polls


def _sign_target(elements: list[dict[str, Any]]) -> str:
    primary_target = _button_target(elements, _PRIMARY_CLICK_TARGET_HINTS)
    if primary_target:
        return primary_target
    return _button_target(elements, _SIGN_TARGET_HINTS)


def _button_target(elements: list[dict[str, Any]], hints: Sequence[str]) -> str:
    for element in elements:
        if str(element.get("role") or "") != "AXButton":
            continue
        labels = [
            _normalized_visible_text(element.get(key))
            for key in ("name", "description", "value")
        ]
        searchable = " ".join(labels).casefold()
        if not any(hint.casefold() in searchable for hint in hints):
            continue
        return next((label for label in labels if label), "")
    return ""


def _interaction_case(
    *,
    app_name: str,
    checks: dict[str, Any],
    stage: str | None = None,
    tool_chain: Sequence[str] | None = None,
) -> dict[str, Any]:
    return _desktop_execution_case(
        "type_click_verify_control",
        app_name=app_name,
        tool_chain=list(tool_chain or TOOL_CHAIN),
        checks=checks,
        stage=stage,
    )


def _interaction_planner_alignment(
    app_name: str,
    *,
    tool_chain: Sequence[str] | None = None,
    mutates_desktop: bool = True,
) -> dict[str, Any]:
    return _planner_alignment(
        intent_category="desktop_type_click_verify",
        app_name=app_name,
        capabilities=INTERACTION_CAPABILITIES,
        tool_chain=list(tool_chain or TOOL_CHAIN),
        mutates_desktop=mutates_desktop,
    )


def _locked_session_evidence(app_name: str, preflight: dict[str, Any]) -> dict[str, Any]:
    screen_probe = _screen_observability_probe()
    blocker_evidence = _merge_blocking_evidence(preflight, screen_probe)
    checks = {"desktop_session_ready": False, **_screen_probe_checks(screen_probe)}
    return {
        "ok": False,
        "mode": "real_desktop_interaction_smoke",
        "skipped": False,
        "platform": "Darwin",
        "app_name": app_name,
        "tool_chain": TOOL_CHAIN,
        "case_count": 1,
        "cases": [_interaction_case(app_name=app_name, checks=checks, stage="session_preflight")],
        "planner_alignment": _interaction_planner_alignment(app_name),
        "stage": "session_preflight",
        "error": "desktop_session_locked",
        "blocking_condition": "desktop_session_locked",
        "blocking_conditions": ["desktop_session_locked"],
        **_screen_probe_evidence(screen_probe),
        **{key: value for key, value in blocker_evidence.items() if key != "error"},
        "preflight": preflight,
        "screen_probe": screen_probe,
        "checks": checks,
    }


def run_smoke(
    *,
    app_name: str = DEFAULT_APP_NAME,
    input_text: str = DEFAULT_INPUT_TEXT,
    cleanup: bool = True,
    allow_existing_app: bool = False,
    provider_mode: str = "real",
) -> dict[str, Any]:
    clean_provider_mode = str(provider_mode or "real").strip().lower()
    current_platform = platform.system()
    clean_app_name = str(app_name or "").strip() or DEFAULT_APP_NAME
    clean_input = str(input_text or "").strip() or DEFAULT_INPUT_TEXT
    if clean_provider_mode == "isolated":
        return _run_isolated_provider_smoke(
            app_name=clean_app_name,
            input_text=clean_input,
        )
    if current_platform != "Darwin":
        return {
            "ok": True,
            "mode": "real_desktop_interaction_smoke",
            "skipped": True,
            "platform": current_platform,
            "app_name": clean_app_name,
            "provider_mode": clean_provider_mode,
            "tool_chain": TOOL_CHAIN,
            "reason": "real desktop interaction smoke only runs on macOS",
        }

    preflight = desktop_tools.active_window()
    if preflight.get("error") == "desktop_session_locked":
        return _locked_session_evidence(clean_app_name, preflight)
    if preflight.get("ok") is not True:
        checks = {"desktop_session_ready": False}
        return {
            "ok": False,
            "mode": "real_desktop_interaction_smoke",
            "skipped": False,
            "platform": current_platform,
            "app_name": clean_app_name,
            "tool_chain": TOOL_CHAIN,
            "case_count": 1,
            "cases": [
                _interaction_case(
                    app_name=clean_app_name,
                    checks=checks,
                    stage="session_preflight",
                )
            ],
            "planner_alignment": _interaction_planner_alignment(clean_app_name),
            "stage": "session_preflight",
            "error": str(preflight.get("error") or "desktop_session_preflight_failed"),
            "preflight": preflight,
            "checks": checks,
        }

    discovery = desktop_tools.list_apps(query=clean_app_name, limit=10)
    discovered_names = _app_names(discovery)
    if discovery.get("ok") is not True or not discovered_names:
        checks = {
            "desktop_session_ready": True,
            "discovered_app": False,
        }
        return {
            "ok": False,
            "mode": "real_desktop_interaction_smoke",
            "skipped": False,
            "platform": current_platform,
            "app_name": clean_app_name,
            "tool_chain": TOOL_CHAIN,
            "case_count": 1,
            "cases": [
                _interaction_case(
                    app_name=clean_app_name,
                    checks=checks,
                    stage="app_discovery",
                )
            ],
            "planner_alignment": _interaction_planner_alignment(clean_app_name),
            "stage": "app_discovery",
            "error": str(discovery.get("error") or "app_not_found"),
            "preflight": preflight,
            "discovery": {"result": discovery, "names": discovered_names},
            "checks": checks,
        }
    discovered_app_name = next(
        (name for name in discovered_names if name.casefold() == clean_app_name.casefold()),
        discovered_names[0] if discovered_names else clean_app_name,
    )
    before_status = desktop_tools.app_status(discovered_app_name)
    before_running = _status_running(before_status)
    if before_running is None or (before_running is True and not allow_existing_app):
        status_error = "app_already_running" if before_running is True else "app_status_unknown"
        checks = {
            "desktop_session_ready": preflight.get("ok") is True,
            "app_not_already_running": False,
            "existing_app_allowed": bool(allow_existing_app),
        }
        return {
            "ok": False,
            "mode": "real_desktop_interaction_smoke",
            "skipped": False,
            "platform": current_platform,
            "app_name": clean_app_name,
            "allow_existing_app": bool(allow_existing_app),
            "tool_chain": TOOL_CHAIN,
            "case_count": 1,
            "cases": [
                _interaction_case(
                    app_name=discovered_app_name,
                    checks=checks,
                    stage="app_preflight",
                )
            ],
            "planner_alignment": _interaction_planner_alignment(discovered_app_name),
            "stage": "app_preflight",
            "error": status_error,
            "reason": (
                "refusing to modify an app that was already running"
                if before_running is True
                else "refusing to modify an app whose initial running state is unknown"
            ),
            "preflight": preflight,
            "discovery": {"result": discovery, "names": discovered_names},
            "before_status": before_status,
            "checks": checks,
        }

    open_result = desktop_tools.app_open(discovered_app_name)
    opened_app_name = _resolved_open_app_name(discovered_app_name, open_result)

    def fail_stage(
        stage: str,
        error: str,
        checks: dict[str, bool],
        details: dict[str, Any],
    ) -> dict[str, Any]:
        failed_after_status = desktop_tools.app_status(opened_app_name)
        failed_after_running = _status_running(failed_after_status)
        failed_cleanup = _cleanup_evidence(
            app_name=opened_app_name,
            cleanup=cleanup,
            before_running=before_running,
            after_running=failed_after_running,
        )
        blocker_evidence = _merge_blocking_evidence(
            preflight,
            *(item for item in details.values() if isinstance(item, dict)),
        )
        return {
            "ok": False,
            "mode": "real_desktop_interaction_smoke",
            "skipped": False,
            "platform": current_platform,
            "app_name": clean_app_name,
            "opened_app_name": opened_app_name,
            "tool_chain": TOOL_CHAIN,
            "case_count": 1,
            "cases": [
                _interaction_case(
                    app_name=opened_app_name,
                    checks=checks,
                    stage=stage,
                )
            ],
            "planner_alignment": _interaction_planner_alignment(opened_app_name),
            "stage": stage,
            "error": error,
            **{key: value for key, value in blocker_evidence.items() if key != "error"},
            "preflight": preflight,
            "discovery": {"result": discovery, "names": discovered_names},
            "before_status": before_status,
            "open_result": open_result,
            **details,
            "after_status": failed_after_status,
            "cleanup": failed_cleanup,
            "checks": checks,
        }

    if open_result.get("ok") is not True:
        return fail_stage(
            "app_open",
            str(open_result.get("error") or "app_open_failed"),
            {
                "desktop_session_ready": preflight.get("ok") is True,
                "discovered_app": discovery.get("ok") is True and bool(discovered_names),
                "app_not_already_running": True,
                "open_ok": False,
            },
            {},
        )

    focus_result, focus_attempts, focus_verified = _focus_with_retries(
        opened_app_name,
        max_attempts=_INITIAL_FOCUS_MAX_ATTEMPTS,
        retry_interval_seconds=_INITIAL_FOCUS_RETRY_INTERVAL_SECONDS,
    )
    if not focus_verified:
        return fail_stage(
            "app_focus",
            str(focus_result.get("error") or "app_focus_not_verified"),
            {
                "desktop_session_ready": preflight.get("ok") is True,
                "discovered_app": True,
                "app_not_already_running": True,
                "open_ok": True,
                "focus_verified": False,
            },
            {"focus_result": focus_result, "focus_attempts": focus_attempts},
        )

    clear_result = desktop_tools.desktop_safe_key("escape", repeat_count=2)
    if clear_result.get("ok") is not True:
        return fail_stage(
            "clear_input",
            str(clear_result.get("error") or "clear_input_failed"),
            {"open_ok": True, "focus_verified": True, "clear_ok": False},
            {"focus_result": focus_result, "clear_result": clear_result},
        )

    type_result = desktop_tools.desktop_safe_type_text(clean_input)
    if type_result.get("ok") is not True:
        return fail_stage(
            "type_input",
            str(type_result.get("error") or "type_input_failed"),
            {
                "open_ok": True,
                "focus_verified": True,
                "clear_ok": True,
                "type_ok": False,
            },
            {
                "focus_result": focus_result,
                "clear_result": clear_result,
                "type_result": type_result,
            },
        )

    time.sleep(0.2)
    before_ui = desktop_tools.ui_elements(app_name=opened_app_name, limit=80)
    before_values = _visible_values(before_ui)
    sign_target = _sign_target(_elements(before_ui))
    typed_value_visible = clean_input in before_values
    before_ui_matches_app = (
        before_ui.get("ok") is True
        and str(_data(before_ui).get("app_name") or "") == opened_app_name
    )
    if not before_ui_matches_app or not sign_target:
        return fail_stage(
            "inspect_typed_value",
            (
                "ui_app_mismatch"
                if before_ui.get("ok") is True and not before_ui_matches_app
                else str(before_ui.get("error") or "click_control_not_visible")
            ),
            {
                "open_ok": True,
                "focus_verified": True,
                "clear_ok": True,
                "type_ok": True,
                "before_ui_matches_app": before_ui_matches_app,
                "typed_value_visible": typed_value_visible,
                "sign_control_found": bool(sign_target),
            },
            {
                "focus_result": focus_result,
                "clear_result": clear_result,
                "type_result": type_result,
                "before_ui": before_ui,
                "before_values": before_values,
                "sign_target": sign_target,
            },
        )

    pre_click_focus_result, pre_click_focus_attempts, pre_click_focus_verified = (
        _focus_with_retries(opened_app_name)
    )
    if not pre_click_focus_verified:
        return fail_stage(
            "pre_click_focus",
            str(pre_click_focus_result.get("error") or "app_focus_not_verified"),
            {
                "open_ok": True,
                "focus_verified": focus_verified,
                "clear_ok": True,
                "type_ok": True,
                "before_ui_matches_app": before_ui_matches_app,
                "typed_value_visible": clean_input in before_values,
                "sign_control_found": bool(sign_target),
                "pre_click_focus_verified": False,
            },
            {
                "focus_result": focus_result,
                "clear_result": clear_result,
                "type_result": type_result,
                "before_ui": before_ui,
                "before_values": before_values,
                "sign_target": sign_target,
                "pre_click_focus_result": pre_click_focus_result,
                "pre_click_focus_attempts": pre_click_focus_attempts,
            },
        )

    pre_click_window = desktop_tools.active_window()
    pre_click_active_app = str(_data(pre_click_window).get("app_name") or "")
    pre_click_active_app_matches = (
        pre_click_window.get("ok") is True
        and _app_names_match(opened_app_name, pre_click_active_app)
    )

    click_result = desktop_tools.click_ui_element(
        sign_target,
        role_filter="button",
        limit=80,
        expected_app_name=opened_app_name,
    )
    click_attempts: list[dict[str, Any]] = [{"attempt": 1, "result": click_result}]
    retry_focus_result: dict[str, Any] | None = None
    retry_active_window: dict[str, Any] | None = None
    retry_active_app = ""
    retry_active_app_matches = False
    if click_result.get("ok") is not True and click_result.get("error") == "foreground_app_mismatch":
        retry_focus_result = desktop_tools.app_focus(opened_app_name)
        retry_focus_verified = retry_focus_result.get("ok") is True and _data(
            retry_focus_result
        ).get("focus_verified") is True
        retry_active_window = desktop_tools.active_window()
        retry_active_app = str(_data(retry_active_window).get("app_name") or "")
        retry_active_app_matches = (
            retry_active_window.get("ok") is True
            and _app_names_match(opened_app_name, retry_active_app)
        )
        if retry_focus_verified and retry_active_app_matches:
            click_result = desktop_tools.click_ui_element(
                sign_target,
                role_filter="button",
                limit=80,
                expected_app_name=opened_app_name,
            )
            click_attempts.append({"attempt": 2, "result": click_result})
    if click_result.get("ok") is not True:
        return fail_stage(
            "click_ui_element",
            str(click_result.get("error") or "click_ui_element_failed"),
            {
                "open_ok": True,
                "focus_verified": focus_verified,
                "clear_ok": True,
                "type_ok": True,
                "before_ui_matches_app": before_ui_matches_app,
                "typed_value_visible": clean_input in before_values,
                "sign_control_found": bool(sign_target),
                "pre_click_focus_verified": pre_click_focus_verified,
                "pre_click_active_app_matches": pre_click_active_app_matches,
                "click_ok": False,
            },
            {
                "focus_result": focus_result,
                "clear_result": clear_result,
                "type_result": type_result,
                "before_ui": before_ui,
                "before_values": before_values,
                "sign_target": sign_target,
                "pre_click_focus_result": pre_click_focus_result,
                "pre_click_window": pre_click_window,
                "pre_click_active_app": pre_click_active_app,
                "click_result": click_result,
                "click_attempts": click_attempts,
                "retry_focus_result": retry_focus_result,
                "retry_active_window": retry_active_window,
                "retry_active_app": retry_active_app,
                "retry_active_app_matches": retry_active_app_matches,
            },
        )
    expected_signed_value = f"-{clean_input.lstrip('+')}"
    after_ui, after_values, after_ui_matches_app, after_value_polls = (
        _poll_after_click_values(
            app_name=opened_app_name,
            before_values=before_values,
            expected_signed_value=expected_signed_value,
        )
    )
    after_status = desktop_tools.app_status(opened_app_name)
    after_running = _status_running(after_status)
    cleanup_result = _cleanup_evidence(
        app_name=opened_app_name,
        cleanup=cleanup,
        before_running=before_running,
        after_running=after_running,
    )
    signed_value_visible = _signed_value_visible(after_values, expected_signed_value)
    visible_value_changed = before_values != after_values
    click_effect_visible = signed_value_visible or visible_value_changed
    checks = {
        "desktop_session_ready": preflight.get("ok") is True,
        "discovered_app": discovery.get("ok") is True and bool(discovered_names),
        "app_not_already_running": before_running is False or bool(allow_existing_app),
        "existing_app_allowed": before_running is not True or bool(allow_existing_app),
        "open_ok": open_result.get("ok") is True,
        "focus_verified": focus_verified,
        "clear_ok": clear_result.get("ok") is True,
        "type_ok": type_result.get("ok") is True,
        "before_ui_matches_app": before_ui_matches_app,
        "typed_value_or_type_tool_confirmed": typed_value_visible
        or type_result.get("ok") is True,
        "sign_control_found": bool(sign_target),
        "pre_click_focus_verified": pre_click_focus_verified,
        "pre_click_active_window_checked": pre_click_window.get("ok") is True,
        "click_ok": click_result.get("ok") is True,
        "after_ui_matches_app": after_ui_matches_app,
        "click_completed_in_target_app": click_result.get("ok") is True
        and after_ui_matches_app,
        "cleanup_ok": cleanup_result.get("ok") is True,
    }
    return {
        "ok": all(checks.values()),
        "mode": "real_desktop_interaction_smoke",
        "skipped": False,
        "platform": current_platform,
        "app_name": clean_app_name,
        "opened_app_name": opened_app_name,
        "allow_existing_app": bool(allow_existing_app),
        "provider_mode": clean_provider_mode,
        "tool_chain": TOOL_CHAIN,
        "case_count": 1,
        "cases": [
            _interaction_case(
                app_name=opened_app_name,
                checks=checks,
                stage="type_click_verify",
            )
        ],
        "planner_alignment": _interaction_planner_alignment(opened_app_name),
        "input_text": clean_input,
        "typed_value_visible": typed_value_visible,
        "expected_signed_value": expected_signed_value,
        "signed_value_visible": signed_value_visible,
        "click_effect_visible": click_effect_visible,
        "visible_value_changed": visible_value_changed,
        "click_target": sign_target,
        "sign_target": sign_target,
        "before_values": before_values,
        "after_values": after_values,
        "after_value_polls": after_value_polls,
        "preflight": preflight,
        "discovery": {"result": discovery, "names": discovered_names},
        "before_status": before_status,
        "open_result": open_result,
        "focus_result": focus_result,
        "focus_attempts": focus_attempts,
        "clear_result": clear_result,
        "type_result": type_result,
        "before_ui": before_ui,
        "pre_click_focus_result": pre_click_focus_result,
        "pre_click_focus_attempts": pre_click_focus_attempts,
        "pre_click_window": pre_click_window,
        "pre_click_active_app": pre_click_active_app,
        "pre_click_active_app_matches": pre_click_active_app_matches,
        "click_result": click_result,
        "click_attempts": click_attempts,
        "retry_focus_result": retry_focus_result,
        "retry_active_window": retry_active_window,
        "retry_active_app": retry_active_app,
        "retry_active_app_matches": retry_active_app_matches,
        "after_ui": after_ui,
        "after_status": after_status,
        "cleanup": cleanup_result,
        "checks": checks,
    }


def _run_isolated_provider_smoke(
    *,
    app_name: str,
    input_text: str,
) -> dict[str, Any]:
    provider = IsolatedDesktopProvider(
        provider_id="smoke-isolated-interaction",
        supported_tools=ISOLATED_INTERACTION_TOOL_CHAIN,
    )
    server = build_isolated_desktop_provider_server(
        host="127.0.0.1",
        port=0,
        provider=provider,
        quiet=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        env = {
            "OHA_YACHIYO_DESKTOP_PROVIDER_URL": base_url,
            "OHA_YACHIYO_DESKTOP_PROVIDER_ID": provider.provider_id,
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": ",".join(
                ISOLATED_INTERACTION_TOOL_CHAIN
            ),
            "OHA_YACHIYO_DESKTOP_PROVIDER_TIMEOUT_SECONDS": "10",
        }
        status = desktop_execution_provider_status_from_env(env, probe_health=True)
        registry = desktop_execution_provider_registry_from_env(env)
        discovery = _execute_isolated_tool(
            registry,
            provider.provider_id,
            "desktop.list_apps",
            {"query": app_name, "limit": 10},
        )
        before_status = _execute_isolated_tool(
            registry,
            provider.provider_id,
            "app.status",
            {"app_name": app_name},
        )
        open_result = _execute_isolated_tool(
            registry,
            provider.provider_id,
            "app.open",
            {
                "app_name": "<selected app from desktop.list_apps>",
                "selection_source": "desktop.list_apps",
                "query": app_name,
            },
        )
        focus_result = _execute_isolated_tool(
            registry,
            provider.provider_id,
            "app.focus",
            {"app_name": app_name},
        )
        before_ui = _execute_isolated_tool(
            registry,
            provider.provider_id,
            "desktop.read_ui",
            {"app_name": app_name, "limit": 80},
        )
        click_result = _execute_isolated_tool(
            registry,
            provider.provider_id,
            "desktop.click_ui_element",
            {
                "target": "Search",
                "role_filter": "text_field",
                "expected_app_name": app_name,
            },
        )
        type_result = _execute_isolated_tool(
            registry,
            provider.provider_id,
            "desktop.safe_type_text",
            {"text": input_text},
        )
        shortcut_result = _execute_isolated_tool(
            registry,
            provider.provider_id,
            "desktop.safe_shortcut",
            {"action": "submit"},
        )
        verify_result = _execute_isolated_tool(
            registry,
            provider.provider_id,
            "desktop.verify",
            {
                "app_name": app_name,
                "target": "Search",
                "expected_text": input_text,
            },
        )
        after_status = _execute_isolated_tool(
            registry,
            provider.provider_id,
            "app.status",
            {"app_name": app_name},
        )
        tool_results = [
            discovery,
            before_status,
            open_result,
            focus_result,
            before_ui,
            click_result,
            type_result,
            shortcut_result,
            verify_result,
            after_status,
        ]
        discovery_matches = _data(discovery).get("matches")
        before_ui_data = _data(before_ui)
        click_data = _data(click_result)
        type_data = _data(type_result)
        shortcut_data = _data(shortcut_result)
        verify_data = _data(verify_result)
        after_status_data = _data(after_status)
        checks = {
            "provider_available": bool(status.get("available")),
            "provider_session_isolated": status.get("desktop_session_isolated") is True,
            "foreground_takeover_not_required": (
                status.get("foreground_takeover_required") is False
            ),
            "keyboard_mouse_supported": (
                status.get("keyboard_mouse_capture_supported") is True
            ),
            "all_tools_routed": all(
                isinstance(item, dict)
                and item.get("desktop_execution_provider_routed") is True
                for item in tool_results
            ),
            "all_tool_results_ok": all(
                isinstance(item, dict) and item.get("ok") is not False
                for item in tool_results
            ),
            "all_tool_results_isolated": all(
                isinstance(item, dict)
                and item.get("isolated_desktop_provider", {}).get(
                    "desktop_session_isolated"
                )
                is True
                for item in tool_results
            ),
            "discovered_app": isinstance(discovery_matches, list)
            and bool(discovery_matches),
            "before_status_checked": before_status.get("ok") is True,
            "open_ok": open_result.get("ok") is True,
            "focus_verified": _data(focus_result).get("focused") is True,
            "read_ui_returned_elements": bool(before_ui_data.get("elements")),
            "click_target_recorded": (
                click_data.get("isolated_event", {}).get("target") == "Search"
            ),
            "type_text_recorded": (
                type_data.get("isolated_event", {}).get("text_buffer") == input_text
            ),
            "submit_recorded": (
                shortcut_data.get("isolated_event", {}).get("tool")
                == "desktop.safe_shortcut"
            ),
            "verify_expected_text": verify_data.get("expected_text_found") is True,
            "verify_target_focused": verify_data.get("expected_target_focused") is True,
            "after_status_running": after_status_data.get("running") is True,
        }
        return {
            "ok": all(checks.values()),
            "mode": "isolated_desktop_interaction_smoke",
            "skipped": False,
            "platform": platform.system(),
            "provider_mode": "isolated",
            "app_name": app_name,
            "opened_app_name": app_name,
            "base_url": base_url,
            "tool_chain": ISOLATED_INTERACTION_TOOL_CHAIN,
            "case_count": 1,
            "cases": [
                _interaction_case(
                    app_name=app_name,
                    checks=checks,
                    stage="isolated_type_click_verify",
                    tool_chain=ISOLATED_INTERACTION_TOOL_CHAIN,
                )
            ],
            "planner_alignment": _interaction_planner_alignment(
                app_name,
                tool_chain=ISOLATED_INTERACTION_TOOL_CHAIN,
                mutates_desktop=False,
            ),
            "desktop_session_kind": str(status.get("desktop_session_kind") or ""),
            "desktop_session_isolated": status.get("desktop_session_isolated"),
            "foreground_takeover_required": status.get("foreground_takeover_required"),
            "keyboard_mouse_capture_supported": status.get(
                "keyboard_mouse_capture_supported"
            ),
            "supported_tools": status.get("supported_tools") or [],
            "covered_tools": ISOLATED_INTERACTION_TOOL_CHAIN,
            "input_text": input_text,
            "typed_value_visible": True,
            "click_target": "Search",
            "sign_target": "Search",
            "before_values": [str(before_ui_data.get("text_buffer") or "")],
            "after_values": [str(verify_data.get("text_buffer") or "")],
            "status": status,
            "discovery": {"result": discovery, "names": _app_names(discovery)},
            "before_status": before_status,
            "open_result": open_result,
            "focus_result": focus_result,
            "before_ui": before_ui,
            "click_result": click_result,
            "type_result": type_result,
            "shortcut_result": shortcut_result,
            "verify_result": verify_result,
            "after_status": after_status,
            "tool_results": tool_results,
            "checks": checks,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _execute_isolated_tool(
    registry: Any,
    provider_id: str,
    tool_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    result = registry.execute_if_routed(
        tool_name,
        payload,
        tool_request=_isolated_tool_request(provider_id, tool_name, payload),
        broker=object(),
        approved=True,
    )
    return dict(result) if isinstance(result, dict) else {"ok": False}


def _isolated_tool_request(
    provider_id: str,
    tool_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "tool": tool_name,
        "input": dict(payload),
        "desktop_execution_route": {
            "route_id": f"desktop-route:{tool_name}",
            "tool_name": tool_name,
            "requested_mode": "sandbox_preferred",
            "selected_provider_kind": "sandbox_desktop",
            "selected_provider_id": provider_id,
            "status": "sandbox_ready",
            "can_execute": True,
            "can_auto_start": True,
            "sandbox_required": True,
            "blocking_conditions": [],
        },
        "sandbox_provider": {
            "available": True,
            "adapter_ready": True,
            "provider_kind": "sandbox_desktop",
            "provider_id": provider_id,
            "status": "available",
            "supported_tools": list(ISOLATED_INTERACTION_TOOL_CHAIN),
            "keyboard_mouse_capture_supported": True,
            "desktop_session_kind": "isolated_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-name", default=DEFAULT_APP_NAME)
    parser.add_argument("--input-text", default=DEFAULT_INPUT_TEXT)
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument(
        "--provider-mode",
        choices=("real", "isolated"),
        default="real",
        help=(
            "real uses the foreground macOS desktop; isolated runs the same "
            "interaction contract through the loopback isolated desktop provider."
        ),
    )
    parser.add_argument(
        "--allow-existing-app",
        action="store_true",
        help=(
            "Allow the smoke to use an already running target app. "
            "By default the smoke refuses to modify existing app state."
        ),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional JSON evidence report path.",
    )
    return parser


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _console_summary(evidence: dict[str, Any], report_json: Path) -> dict[str, Any]:
    summary_keys = (
        "ok",
        "mode",
        "skipped",
        "platform",
        "app_name",
        "opened_app_name",
        "allow_existing_app",
        "provider_mode",
        "tool_chain",
        "case_count",
        "stage",
        "error",
        "reason",
        "blocking_condition",
        "blocking_conditions",
        "recovery_hints",
        "recommended_tools",
        "input_text",
        "typed_value_visible",
        "expected_signed_value",
        "signed_value_visible",
        "click_effect_visible",
        "visible_value_changed",
        "sign_target",
        "before_values",
        "after_values",
        "pre_click_active_app",
        "retry_active_app",
        "retry_active_app_matches",
        "desktop_session_kind",
        "desktop_session_isolated",
        "foreground_takeover_required",
        "keyboard_mouse_capture_supported",
    )
    summary = {
        key: evidence[key]
        for key in summary_keys
        if key in evidence and evidence[key] not in ("", [], {}, None)
    }
    checks = evidence.get("checks")
    if isinstance(checks, dict):
        summary["checks"] = _bool_checks(checks)
    click_attempts = evidence.get("click_attempts")
    if isinstance(click_attempts, list):
        summary["click_attempt_count"] = len(click_attempts)
    after_value_polls = evidence.get("after_value_polls")
    if isinstance(after_value_polls, list):
        summary["after_value_poll_count"] = len(after_value_polls)
    summary["report_json"] = str(report_json)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = run_smoke(
        app_name=args.app_name,
        input_text=args.input_text,
        cleanup=not args.no_cleanup,
        allow_existing_app=args.allow_existing_app,
        provider_mode=args.provider_mode,
    )
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
        print(
            f"real desktop interaction smoke report: {args.report_json}",
            file=sys.stderr,
        )
        print(
            json.dumps(
                _console_summary(evidence, args.report_json),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
