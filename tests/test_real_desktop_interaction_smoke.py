from __future__ import annotations

import json

from scripts import smoke_real_desktop_interaction as smoke


def test_real_desktop_interaction_smoke_skips_non_macos(monkeypatch):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert evidence["skipped"] is True
    assert evidence["mode"] == "real_desktop_interaction_smoke"


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

    evidence = smoke.run_smoke()

    assert evidence["ok"] is False
    assert evidence["stage"] == "session_preflight"
    assert evidence["error"] == "desktop_session_locked"
    assert evidence["blocking_condition"] == "desktop_session_locked"
    assert evidence["blocking_conditions"] == ["desktop_session_locked"]
    assert evidence["checks"] == {"desktop_session_ready": False}


def test_real_desktop_interaction_smoke_types_clicks_and_verifies(monkeypatch):
    calls: list[tuple] = []
    statuses = iter([False, True, False])
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
    monkeypatch.setattr(
        smoke.desktop_tools,
        "click_ui_element",
        lambda target, **kwargs: calls.append(("click", target, kwargs)) or {"ok": True},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda app_name: {"ok": True, "data": {"app_name": app_name, "running": False}},
    )

    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert evidence["before_values"] == ["42"]
    assert evidence["after_values"] == ["(-42)"]
    assert evidence["tool_chain"] == smoke.TOOL_CHAIN
    assert evidence["checks"]["signed_value_visible"] is True
    assert evidence["sign_target"] == "更改数值符号"
    assert all(evidence["checks"].values())
    assert calls == [
        ("key", "escape", 2),
        ("type", "42"),
        ("click", "更改数值符号", {"role_filter": "button", "limit": 80}),
    ]


def test_real_desktop_interaction_smoke_stops_if_active_app_changes_before_click(
    monkeypatch,
):
    statuses = iter([False, True, False])
    active_windows = iter(
        [
            {"ok": True, "data": {"app_name": "Codex"}},
            {"ok": True, "data": {"app_name": "QQ"}},
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
        lambda **_kwargs: {
            "ok": True,
            "data": {
                "app_name": "Calculator",
                "elements": [
                    {"role": "AXStaticText", "name": "\u200e42", "value": "\u200e42"},
                    {"role": "AXButton", "name": "更改数值符号", "description": "按钮"},
                ],
            },
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "click_ui_element",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not click after foreground app changed")
        ),
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda app_name: {"ok": True, "data": {"app_name": app_name, "running": False}},
    )

    evidence = smoke.run_smoke()

    assert evidence["ok"] is False
    assert evidence["stage"] == "pre_click_active_window"
    assert evidence["error"] == "foreground_app_mismatch_before_click"
    assert evidence["tool_chain"] == smoke.TOOL_CHAIN
    assert evidence["pre_click_active_app"] == "QQ"
    assert evidence["checks"]["pre_click_focus_verified"] is True
    assert evidence["checks"]["pre_click_active_app_matches"] is False
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
    assert output == report
    assert report["ok"] is True
    assert report["mode"] == "real_desktop_interaction_smoke"
    assert report["skipped"] is True
    assert "real desktop interaction smoke report:" in captured.err
    assert str(report_path) in captured.err
