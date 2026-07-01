from __future__ import annotations

import json

from scripts import smoke_real_desktop_interaction as smoke


def test_real_desktop_interaction_smoke_skips_non_macos(monkeypatch):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert evidence["skipped"] is True
    assert evidence["mode"] == "real_desktop_interaction_smoke"


def test_real_desktop_interaction_smoke_prefers_backspace_click_target():
    target = smoke._sign_target(
        [
            {"role": "AXButton", "name": "更改数值符号", "description": "按钮"},
            {
                "role": "AXButton",
                "name": "删除输入的上个数字或操作（长按全部删除）",
                "description": "按钮",
            },
        ]
    )

    assert target == "删除输入的上个数字或操作（长按全部删除）"


def test_real_desktop_interaction_smoke_stops_before_app_mutation_when_locked(monkeypatch):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        smoke.desktop_tools,
        "active_window",
        lambda: {
            "ok": False,
            "action": "desktop.active_window",
            "error": "desktop_session_locked",
            "data": {"frontmost_app": "loginwindow"},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not discover apps while locked")),
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "screen_capture",
        lambda _target: {
            "ok": True,
            "action": "screen.capture",
            "summary": "Captured blank screen",
            "blocking_condition": "screen_capture_blank",
            "data": {
                "visibility_status": "blank_black",
                "blank_frame": True,
                "blocking_condition": "screen_capture_blank",
            },
            "recommended_tools": ["desktop.active_window", "desktop.permissions"],
        },
    )

    evidence = smoke.run_smoke()

    assert evidence["ok"] is False
    assert evidence["stage"] == "session_preflight"
    assert evidence["error"] == "desktop_session_locked"
    assert evidence["blocking_condition"] == "desktop_session_locked"
    assert evidence["blocking_conditions"] == [
        "desktop_session_locked",
        "screen_capture_blank",
    ]
    assert evidence["screen_visibility_status"] == "blank_black"
    assert evidence["screen_blocking_condition"] == "screen_capture_blank"
    assert evidence["screen_probe"]["blocking_condition"] == "screen_capture_blank"
    assert evidence["case_count"] == 1
    assert evidence["cases"][0]["id"] == "type_click_verify_control"
    assert evidence["cases"][0]["stage"] == "session_preflight"
    assert evidence["cases"][0]["passed"] is False
    assert evidence["planner_alignment"]["intent_category"] == "desktop_type_click_verify"
    assert evidence["planner_alignment"]["approval_policy"] == {
        "mutates_desktop": True,
        "approval_required": False,
    }
    assert evidence["checks"] == {
        "desktop_session_ready": False,
        "screen_capture_available": True,
        "screen_observable": False,
    }


def test_real_desktop_interaction_smoke_types_clicks_and_verifies(monkeypatch):
    calls: list[tuple] = []
    statuses = iter([False, True, False])
    active_windows = iter(
        [
            {"ok": True, "data": {"app_name": "Codex"}},
            {"ok": True, "data": {"app_name": "Calculator"}},
            {"ok": True, "data": {"app_name": "Calculator"}},
        ]
    )
    ui_results = iter(
        [
            {
                "ok": True,
                "data": {
                    "app_name": "Calculator",
                    "elements": [
                        {"role": "AXStaticText", "name": "\u200e42", "value": "\u200e42"},
                        {"role": "AXButton", "name": "更改数值符号", "description": "按钮"},
                    ],
                },
            },
            {
                "ok": True,
                "data": {
                    "app_name": "Calculator",
                    "elements": [
                        {"role": "AXStaticText", "name": "\u200e42", "value": "\u200e42"},
                    ],
                },
            },
            {
                "ok": True,
                "data": {
                    "app_name": "Calculator",
                    "elements": [
                        {
                            "role": "AXStaticText",
                            "name": "\u200e(\u200e-\u200e42\u200e)",
                            "value": "\u200e(\u200e-\u200e42\u200e)",
                        },
                    ],
                },
            },
        ]
    )
    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(smoke.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        smoke.desktop_tools,
        "active_window",
        lambda: next(active_windows),
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda *, query="", limit=200: {
            "ok": True,
            "data": {"apps": [{"name": "Calculator"}]},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_status",
        lambda app_name: {
            "ok": True,
            "data": {"app_name": app_name, "running": next(statuses)},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {
            "ok": True,
            "data": {"app_name": app_name, "launch_verified": True},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_focus",
        lambda app_name: {
            "ok": True,
            "data": {"app_name": app_name, "focus_verified": True},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "desktop_safe_key",
        lambda action, repeat_count=1: calls.append(("key", action, repeat_count))
        or {"ok": True},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "desktop_safe_type_text",
        lambda text: calls.append(("type", text)) or {"ok": True},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "ui_elements",
        lambda **_kwargs: next(ui_results),
    )
    click_results = iter(
        [
            {
                "ok": False,
                "error": "foreground_app_mismatch",
                "data": {
                    "expected_app_name": "Calculator",
                    "observed_app_name": "QQ",
                },
            },
            {"ok": True},
        ]
    )

    def fake_click_ui_element(target, **kwargs):
        calls.append(("click", target, kwargs))
        return next(click_results)

    monkeypatch.setattr(smoke.desktop_tools, "click_ui_element", fake_click_ui_element)
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda app_name: {"ok": True, "data": {"app_name": app_name, "running": False}},
    )

    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert evidence["before_values"] == ["42"]
    assert evidence["after_values"] == ["(-42)"]
    assert evidence["after_value_polls"] == [
        {
            "attempt": 1,
            "after_ui_matches_app": True,
            "signed_value_visible": False,
            "visible_value_changed": False,
            "click_effect_visible": False,
            "values": ["42"],
        },
        {
            "attempt": 2,
            "after_ui_matches_app": True,
            "signed_value_visible": True,
            "visible_value_changed": True,
            "click_effect_visible": True,
            "values": ["(-42)"],
        }
    ]
    assert evidence["tool_chain"] == smoke.TOOL_CHAIN
    assert evidence["case_count"] == 1
    assert evidence["cases"][0]["id"] == "type_click_verify_control"
    assert evidence["cases"][0]["stage"] == "type_click_verify"
    assert evidence["cases"][0]["app_name"] == "Calculator"
    assert evidence["cases"][0]["tool_chain"] == smoke.TOOL_CHAIN
    assert evidence["cases"][0]["passed"] is True
    assert evidence["planner_alignment"]["capabilities"] == smoke.INTERACTION_CAPABILITIES
    assert evidence["planner_alignment"]["tool_plan"] == [
        {"tool": tool_name} for tool_name in smoke.TOOL_CHAIN
    ]
    assert len(evidence["click_attempts"]) == 2
    assert evidence["click_attempts"][0]["result"]["error"] == "foreground_app_mismatch"
    assert evidence["click_attempts"][1]["result"]["ok"] is True
    assert evidence["retry_active_app_matches"] is True
    assert len(evidence["pre_click_focus_attempts"]) == 1
    assert evidence["signed_value_visible"] is True
    assert evidence["click_effect_visible"] is True
    assert evidence["checks"]["click_completed_in_target_app"] is True
    assert evidence["sign_target"] == "更改数值符号"
    assert all(evidence["checks"].values())
    assert calls == [
        ("key", "escape", 2),
        ("type", "42"),
        (
            "click",
            "更改数值符号",
            {
                "role_filter": "button",
                "limit": 80,
                "expected_app_name": "Calculator",
            },
        ),
        (
            "click",
            "更改数值符号",
            {
                "role_filter": "button",
                "limit": 80,
                "expected_app_name": "Calculator",
            },
        ),
    ]


def test_real_desktop_interaction_smoke_refuses_existing_app_by_default(monkeypatch):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        smoke.desktop_tools,
        "active_window",
        lambda: {"ok": True, "data": {"app_name": "Codex"}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda **_kwargs: {"ok": True, "data": {"apps": [{"name": "Calculator"}]}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_status",
        lambda app_name: {"ok": True, "data": {"app_name": app_name, "running": True}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not mutate an existing app by default")
        ),
    )

    evidence = smoke.run_smoke()

    assert evidence["ok"] is False
    assert evidence["stage"] == "app_preflight"
    assert evidence["error"] == "app_already_running"
    assert evidence["allow_existing_app"] is False
    assert evidence["checks"] == {
        "desktop_session_ready": True,
        "app_not_already_running": False,
        "existing_app_allowed": False,
    }


def test_real_desktop_interaction_smoke_allows_existing_app_when_requested(monkeypatch):
    statuses = iter([True, True])
    active_windows = iter(
        [
            {"ok": True, "data": {"app_name": "Codex"}},
            {"ok": True, "data": {"app_name": "Calculator"}},
        ]
    )
    ui_results = iter(
        [
            {
                "ok": True,
                "data": {
                    "app_name": "Calculator",
                    "elements": [
                        {"role": "AXStaticText", "name": "42", "value": "42"},
                        {"role": "AXButton", "name": "更改数值符号", "description": "按钮"},
                    ],
                },
            },
            {
                "ok": True,
                "data": {
                    "app_name": "Calculator",
                    "elements": [
                        {"role": "AXStaticText", "name": "-42", "value": "-42"},
                    ],
                },
            },
        ]
    )
    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(smoke.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(smoke.desktop_tools, "active_window", lambda: next(active_windows))
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda **_kwargs: {"ok": True, "data": {"apps": [{"name": "Calculator"}]}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_status",
        lambda app_name: {"ok": True, "data": {"app_name": app_name, "running": next(statuses)}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {"ok": True, "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_focus",
        lambda app_name: {"ok": True, "data": {"app_name": app_name, "focus_verified": True}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "desktop_safe_key",
        lambda *_args, **_kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "desktop_safe_type_text",
        lambda _text: {"ok": True},
    )
    monkeypatch.setattr(smoke.desktop_tools, "ui_elements", lambda **_kwargs: next(ui_results))
    monkeypatch.setattr(
        smoke.desktop_tools,
        "click_ui_element",
        lambda *_args, **_kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not quit an app that was already running")
        ),
    )

    evidence = smoke.run_smoke(allow_existing_app=True)

    assert evidence["ok"] is True
    assert evidence["allow_existing_app"] is True
    assert evidence["checks"]["app_not_already_running"] is True
    assert evidence["checks"]["existing_app_allowed"] is True
    assert evidence["click_effect_visible"] is True
    assert evidence["checks"]["click_completed_in_target_app"] is True
    assert evidence["cleanup"]["attempted"] is False
    assert evidence["cleanup"]["reason"] == "app was already running before smoke"
    assert evidence["after_values"] == ["-42"]


def test_real_desktop_interaction_smoke_retries_initial_focus_after_open(monkeypatch):
    statuses = iter([False, True, False])
    active_windows = iter(
        [
            {"ok": True, "data": {"app_name": "Codex"}},
            {"ok": True, "data": {"app_name": "Calculator"}},
        ]
    )
    focus_results = iter(
        [
            {
                "ok": False,
                "error": "app_focus_not_verified",
                "blocking_condition": "foreground_focus_unavailable",
                "data": {
                    "app_name": "Calculator",
                    "frontmost_app": "Fork",
                    "focus_verified": False,
                    "retryable": True,
                },
            },
            {"ok": True, "data": {"app_name": "Calculator", "focus_verified": True}},
            {"ok": True, "data": {"app_name": "Calculator", "focus_verified": True}},
        ]
    )
    ui_results = iter(
        [
            {
                "ok": True,
                "data": {
                    "app_name": "Calculator",
                    "elements": [
                        {"role": "AXStaticText", "name": "42", "value": "42"},
                        {"role": "AXButton", "name": "更改数值符号", "description": "按钮"},
                    ],
                },
            },
            {
                "ok": True,
                "data": {
                    "app_name": "Calculator",
                    "elements": [
                        {"role": "AXStaticText", "name": "-42", "value": "-42"},
                    ],
                },
            },
        ]
    )
    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(smoke.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(smoke.desktop_tools, "active_window", lambda: next(active_windows))
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda **_kwargs: {"ok": True, "data": {"apps": [{"name": "Calculator"}]}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_status",
        lambda app_name: {"ok": True, "data": {"app_name": app_name, "running": next(statuses)}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {"ok": True, "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(smoke.desktop_tools, "app_focus", lambda app_name: next(focus_results))
    monkeypatch.setattr(smoke.desktop_tools, "desktop_safe_key", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(smoke.desktop_tools, "desktop_safe_type_text", lambda _text: {"ok": True})
    monkeypatch.setattr(smoke.desktop_tools, "ui_elements", lambda **_kwargs: next(ui_results))
    monkeypatch.setattr(smoke.desktop_tools, "click_ui_element", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda app_name: {"ok": True, "data": {"app_name": app_name, "running": False}},
    )

    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert [item["focus_verified"] for item in evidence["focus_attempts"]] == [
        False,
        True,
    ]
    assert evidence["checks"]["focus_verified"] is True
    assert evidence["click_effect_visible"] is True
    assert evidence["after_values"] == ["-42"]


def test_real_desktop_interaction_smoke_retries_pre_click_focus(monkeypatch):
    statuses = iter([False, True, False])
    active_windows = iter(
        [
            {"ok": True, "data": {"app_name": "Codex"}},
            {"ok": True, "data": {"app_name": "Calculator"}},
        ]
    )
    focus_results = iter(
        [
            {"ok": True, "data": {"app_name": "Calculator", "focus_verified": True}},
            {
                "ok": False,
                "error": "app_focus_not_verified",
                "blocking_condition": "foreground_focus_unavailable",
                "data": {
                    "app_name": "Calculator",
                    "frontmost_app": "Google Chrome",
                    "focus_verified": False,
                    "retryable": True,
                },
            },
            {"ok": True, "data": {"app_name": "Calculator", "focus_verified": True}},
        ]
    )
    ui_results = iter(
        [
            {
                "ok": True,
                "data": {
                    "app_name": "Calculator",
                    "elements": [
                        {"role": "AXStaticText", "name": "42", "value": "42"},
                        {"role": "AXButton", "name": "更改数值符号", "description": "按钮"},
                    ],
                },
            },
            {
                "ok": True,
                "data": {
                    "app_name": "Calculator",
                    "elements": [
                        {"role": "AXStaticText", "name": "-42", "value": "-42"},
                    ],
                },
            },
        ]
    )
    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(smoke.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(smoke.desktop_tools, "active_window", lambda: next(active_windows))
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda **_kwargs: {"ok": True, "data": {"apps": [{"name": "Calculator"}]}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_status",
        lambda app_name: {"ok": True, "data": {"app_name": app_name, "running": next(statuses)}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {"ok": True, "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(smoke.desktop_tools, "app_focus", lambda app_name: next(focus_results))
    monkeypatch.setattr(smoke.desktop_tools, "desktop_safe_key", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(smoke.desktop_tools, "desktop_safe_type_text", lambda _text: {"ok": True})
    monkeypatch.setattr(smoke.desktop_tools, "ui_elements", lambda **_kwargs: next(ui_results))
    monkeypatch.setattr(smoke.desktop_tools, "click_ui_element", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda app_name: {"ok": True, "data": {"app_name": app_name, "running": False}},
    )

    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert [item["focus_verified"] for item in evidence["pre_click_focus_attempts"]] == [
        False,
        True,
    ]
    assert evidence["checks"]["pre_click_focus_verified"] is True
    assert evidence["click_effect_visible"] is True
    assert evidence["checks"]["click_completed_in_target_app"] is True
    assert evidence["after_values"] == ["-42"]


def test_real_desktop_interaction_smoke_retries_when_click_guard_detects_foreground_change(
    monkeypatch,
):
    statuses = iter([False, True, False])
    active_windows = iter(
        [
            {"ok": True, "data": {"app_name": "Codex"}},
            {"ok": True, "data": {"app_name": "QQ"}},
            {"ok": True, "data": {"app_name": "Calculator"}},
        ]
    )
    ui_results = iter(
        [
            {
                "ok": True,
                "data": {
                    "app_name": "Calculator",
                    "elements": [
                        {"role": "AXStaticText", "name": "\u200e42", "value": "\u200e42"},
                        {"role": "AXButton", "name": "更改数值符号", "description": "按钮"},
                    ],
                },
            },
            {
                "ok": True,
                "data": {
                    "app_name": "Calculator",
                    "elements": [
                        {"role": "AXStaticText", "name": "-42", "value": "-42"},
                    ],
                },
            },
        ]
    )
    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(smoke.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        smoke.desktop_tools,
        "active_window",
        lambda: next(active_windows),
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda *, query="", limit=200: {
            "ok": True,
            "data": {"apps": [{"name": "Calculator"}]},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_status",
        lambda app_name: {
            "ok": True,
            "data": {"app_name": app_name, "running": next(statuses)},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {
            "ok": True,
            "data": {"app_name": app_name, "launch_verified": True},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_focus",
        lambda app_name: {
            "ok": True,
            "data": {"app_name": app_name, "focus_verified": True},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "desktop_safe_key",
        lambda action, repeat_count=1: {"ok": True},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "desktop_safe_type_text",
        lambda text: {"ok": True},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "ui_elements",
        lambda **_kwargs: next(ui_results),
    )
    click_results = iter(
        [
            {
                "ok": False,
                "error": "foreground_app_mismatch",
                "data": {"expected_app_name": "Calculator", "observed_app_name": "QQ"},
            },
            {"ok": True},
        ]
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "click_ui_element",
        lambda *_args, **_kwargs: next(click_results),
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda app_name: {"ok": True, "data": {"app_name": app_name, "running": False}},
    )

    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert evidence["tool_chain"] == smoke.TOOL_CHAIN
    assert evidence["pre_click_active_app"] == "QQ"
    assert evidence["checks"]["pre_click_focus_verified"] is True
    assert evidence["pre_click_active_app_matches"] is False
    assert len(evidence["click_attempts"]) == 2
    assert evidence["click_attempts"][0]["result"]["error"] == "foreground_app_mismatch"
    assert evidence["retry_active_app_matches"] is True
    assert evidence["cleanup"]["attempted"] is True


def test_real_desktop_interaction_smoke_never_types_when_focus_fails(monkeypatch):
    statuses = iter([False, True, False])
    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        smoke.desktop_tools,
        "active_window",
        lambda: {"ok": True, "data": {"app_name": "Codex"}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda **_kwargs: {"ok": True, "data": {"apps": [{"name": "Calculator"}]}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_status",
        lambda app_name: {"ok": True, "data": {"running": next(statuses)}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {"ok": True, "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_focus",
        lambda app_name: {"ok": False, "error": "app_focus_not_verified"},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "desktop_safe_key",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not send keys without verified focus")
        ),
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda app_name: {"ok": True, "data": {"running": False}},
    )

    evidence = smoke.run_smoke()

    assert evidence["ok"] is False
    assert evidence["stage"] == "app_focus"
    assert evidence["error"] == "app_focus_not_verified"
    assert evidence["checks"]["focus_verified"] is False
    assert evidence["cleanup"]["attempted"] is True


def test_real_desktop_interaction_smoke_surfaces_focus_blocker(monkeypatch):
    statuses = iter([False, True, False])
    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        smoke.desktop_tools,
        "active_window",
        lambda: {"ok": True, "data": {"app_name": "Codex"}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda **_kwargs: {"ok": True, "data": {"apps": [{"name": "Calculator"}]}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_status",
        lambda app_name: {"ok": True, "data": {"running": next(statuses)}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {"ok": True, "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_focus",
        lambda app_name: {
            "ok": False,
            "error": "desktop_session_locked",
            "blocking_condition": "desktop_session_locked",
            "data": {"blocking_condition": "desktop_session_locked"},
            "recovery_hints": ["Unlock the active macOS user session, then retry."],
            "recovery_actions": [
                {
                    "label": "解锁后重试Calculator",
                    "tool": "app.focus",
                    "input": {"app_name": "Calculator"},
                    "permission_target": "desktop_session_unlocked",
                    "risk_level": "low",
                }
            ],
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "desktop_safe_key",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not send keys without verified focus")
        ),
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda app_name: {"ok": True, "data": {"running": False}},
    )

    evidence = smoke.run_smoke()

    assert evidence["ok"] is False
    assert evidence["stage"] == "app_focus"
    assert evidence["error"] == "desktop_session_locked"
    assert evidence["blocking_condition"] == "desktop_session_locked"
    assert evidence["blocking_conditions"] == ["desktop_session_locked"]
    assert evidence["recovery_hints"] == ["Unlock the active macOS user session, then retry."]
    assert evidence["recovery_actions"][0]["tool"] == "app.focus"
    assert evidence["case_count"] == 1
    assert evidence["cases"][0]["stage"] == "app_focus"
    assert evidence["cases"][0]["passed"] is False
    assert evidence["checks"]["focus_verified"] is False
    assert evidence["cleanup"]["attempted"] is True


def test_real_desktop_interaction_smoke_cli_outputs_json(monkeypatch, capsys):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    assert smoke.main([]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "real_desktop_interaction_smoke"
    assert output["skipped"] is True


def test_real_desktop_interaction_smoke_cli_writes_report_json(
    monkeypatch,
    tmp_path,
    capsys,
):
    report_path = tmp_path / "real-desktop-interaction.json"
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    assert smoke.main(["--report-json", str(report_path)]) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output != report
    assert output == {
        "ok": True,
        "mode": "real_desktop_interaction_smoke",
        "skipped": True,
        "platform": "Linux",
        "app_name": "Calculator",
        "tool_chain": smoke.TOOL_CHAIN,
        "reason": "real desktop interaction smoke only runs on macOS",
        "report_json": str(report_path),
    }
    assert report["ok"] is True
    assert report["mode"] == "real_desktop_interaction_smoke"
    assert report["skipped"] is True
    assert "real desktop interaction smoke report:" in captured.err
    assert str(report_path) in captured.err


def test_real_desktop_interaction_report_stdout_is_compact_on_blocker(
    monkeypatch,
    tmp_path,
    capsys,
):
    report_path = tmp_path / "real-desktop-interaction.json"

    monkeypatch.setattr(
        smoke,
        "run_smoke",
        lambda **kwargs: {
            "ok": False,
            "mode": "real_desktop_interaction_smoke",
            "skipped": False,
            "platform": "Darwin",
            "app_name": kwargs["app_name"],
            "tool_chain": smoke.TOOL_CHAIN,
            "case_count": 1,
            "stage": "session_preflight",
            "error": "desktop_session_locked",
            "blocking_condition": "desktop_session_locked",
            "blocking_conditions": ["desktop_session_locked"],
            "recovery_hints": [
                "Unlock the active macOS user session, then retry the foreground desktop action."
            ],
            "recommended_tools": ["desktop.active_window"],
            "checks": {"desktop_session_ready": False},
            "preflight": {"data": {"large": ["not for stdout"]}},
            "before_ui": {"data": {"elements": [{"name": "not for stdout"}]}},
            "click_attempts": [
                {"attempt": 1, "result": {"ok": False, "data": {"large": "hidden"}}}
            ],
        },
    )

    assert smoke.main(["--report-json", str(report_path)]) == 1

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output["ok"] is False
    assert output["stage"] == "session_preflight"
    assert output["blocking_condition"] == "desktop_session_locked"
    assert output["recommended_tools"] == ["desktop.active_window"]
    assert output["checks"] == {"desktop_session_ready": False}
    assert output["click_attempt_count"] == 1
    assert "preflight" not in output
    assert "before_ui" not in output
    assert "click_attempts" not in output
    assert report["preflight"]["data"]["large"] == ["not for stdout"]
    assert report["before_ui"]["data"]["elements"] == [{"name": "not for stdout"}]
    assert report["click_attempts"][0]["result"]["data"]["large"] == "hidden"
