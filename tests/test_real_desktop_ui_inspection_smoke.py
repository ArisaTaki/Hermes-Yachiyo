from __future__ import annotations

import json

from scripts import smoke_real_desktop_ui_inspection as smoke


def _patch_verify(monkeypatch, *, ok: bool = True) -> None:
    def fake_inspect_app(
        app_name,
        *,
        open_if_needed=True,
        focus=True,
        role_filter="",
        limit=80,
    ):
        return {
            "ok": ok,
            "action": "desktop.inspect_app",
            "summary": f"Verified {app_name}",
            "data": {
                "app_name": app_name,
                "open_if_needed": open_if_needed,
                "focus_requested": focus,
                "running": ok,
                "checks": {"status_running": ok},
                "ui_element_count": 2 if ok else 0,
            },
            "permission_error": False,
        }

    monkeypatch.setattr(smoke.desktop_tools, "inspect_app", fake_inspect_app)


def test_real_desktop_ui_inspection_smoke_skips_non_macos(monkeypatch):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    evidence = smoke.run_smoke(app_name="Calculator")

    assert evidence == {
        "ok": True,
        "mode": "real_desktop_ui_inspection_smoke",
        "skipped": True,
        "platform": "Linux",
        "app_name": "Calculator",
        "reason": "real desktop UI inspection smoke only runs on macOS",
    }


def test_real_desktop_ui_inspection_smoke_stops_before_app_mutation_when_locked(
    monkeypatch,
):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        smoke.desktop_tools,
        "active_window",
        lambda: {
            "ok": False,
            "action": "desktop.active_window",
            "error": "desktop_session_locked",
            "blocking_condition": "desktop_session_locked",
            "data": {"frontmost_app": "loginwindow"},
            "recovery_actions": [
                {
                    "label": "解锁后重新检查前台窗口",
                    "tool": "desktop.active_window",
                    "input": {},
                    "permission_target": "desktop_session_unlocked",
                    "risk_level": "low",
                }
            ],
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not discover apps while locked")
        ),
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

    evidence = smoke.run_smoke(app_name="Calculator")

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
    assert evidence["cases"][0]["id"] == "inspect_named_app_ui"
    assert evidence["cases"][0]["stage"] == "session_preflight"
    assert evidence["cases"][0]["passed"] is False
    assert evidence["planner_alignment"]["intent_category"] == "desktop_ui_inspection"
    assert evidence["planner_alignment"]["approval_policy"] == {
        "mutates_desktop": True,
        "approval_required": False,
    }
    assert evidence["checks"] == {
        "desktop_session_ready": False,
        "screen_capture_available": True,
        "screen_observable": False,
    }
    assert evidence["preflight"]["error"] == "desktop_session_locked"
    assert evidence["recovery_actions"][0]["tool"] == "desktop.active_window"


def test_real_desktop_ui_inspection_smoke_accepts_menu_level_ui_for_named_app(monkeypatch):
    calls: list[tuple[str, str]] = []
    status_values = iter([False, True, False])

    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda *, query="", limit=200: {
            "ok": True,
            "action": "desktop.list_apps",
            "data": {"query": query, "apps": [{"name": "Oha-Yachiyo"}]},
            "permission_error": False,
        },
    )

    def fake_status(app_name):
        running = next(status_values)
        calls.append(("status", app_name))
        return {
            "ok": True,
            "action": "app.status",
            "data": {
                "app_name": app_name,
                "running": running,
                "status": "running" if running else "not_running",
            },
        }

    monkeypatch.setattr(smoke.desktop_tools, "app_status", fake_status)
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {
            "ok": True,
            "action": "app.open",
            "data": {"app_name": app_name, "launch_verified": True},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "running_apps",
        lambda: {
            "ok": True,
            "action": "desktop.running_apps",
            "data": {"apps": [{"name": "Oha-Yachiyo", "frontmost": False}]},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "windows",
        lambda app_name="": {
            "ok": True,
            "action": "desktop.windows",
            "data": {
                "app_name": app_name,
                "windows": [],
                "count": 0,
                "visibility_limited": True,
                "window_visibility_status": "running_without_visible_windows",
            },
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_focus",
        lambda app_name: {
            "ok": True,
            "action": "app.focus",
            "data": {"app_name": app_name},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "active_window",
        lambda: {
            "ok": True,
            "action": "desktop.active_window",
            "data": {"app_name": "Codex", "title": ""},
        },
    )

    def fake_ui_elements(*, app_name="", role_filter="", limit=80):
        elements = [
            {"depth": 0, "role": "AXMenuBar", "name": "Oha-Yachiyo"},
            {"depth": 1, "role": "AXMenuBarItem", "name": "File"},
        ]
        if role_filter == "menu":
            elements = [element for element in elements if "Menu" in element["role"]]
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "data": {
                "app_name": app_name,
                "title": "",
                "elements": elements,
                "count": len(elements),
                "role_filter": role_filter,
                "limit": limit,
                "role_counts": {"AXMenuBar": 1, "AXMenuBarItem": 1},
                "unclassified_count": 0,
                "menu_level_count": len(elements),
                "control_like_count": 0,
                "inspection_level": "menu",
                "visibility_status": "menu_level_only",
                "visibility_limited": True,
            },
        }

    monkeypatch.setattr(smoke.desktop_tools, "ui_elements", fake_ui_elements)
    _patch_verify(monkeypatch)
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda app_name: {
            "ok": True,
            "action": "app.quit",
            "data": {"app_name": app_name, "quit_verified": True, "running": False},
        },
    )

    evidence = smoke.run_smoke(app_name="Oha-Yachiyo", cleanup=True)

    assert evidence["ok"] is True
    assert evidence["tool_chain"] == [
        "desktop.list_apps",
        "desktop.open_app",
        "desktop.running_apps",
        "desktop.list_windows",
        "desktop.focus_app",
        "desktop.active_window",
        "desktop.read_ui",
        "desktop.read_ui",
        "desktop.verify",
        "app.status",
    ]
    assert evidence["open_result"]["action"] == "desktop.open_app"
    assert evidence["windows"]["action"] == "desktop.list_windows"
    assert evidence["focus_result"]["action"] == "desktop.focus_app"
    assert evidence["ui_elements"]["action"] == "desktop.read_ui"
    assert evidence["verify_result"]["action"] == "desktop.verify"
    assert evidence["case_count"] == 1
    assert evidence["cases"][0]["id"] == "inspect_named_app_ui"
    assert evidence["cases"][0]["tool_chain"] == evidence["tool_chain"]
    assert evidence["cases"][0]["passed"] is True
    assert evidence["planner_alignment"]["intent_category"] == "desktop_ui_inspection"
    assert evidence["planner_alignment"]["capabilities"] == [
        "desktop.app_discovery",
        "desktop.app_launch",
        "desktop.window_focus",
        "desktop.ui_inspection",
        "desktop.app_verification",
    ]
    assert evidence["planner_alignment"]["approval_policy"] == {
        "mutates_desktop": True,
        "approval_required": False,
    }
    assert evidence["focus_verified"] is False
    assert evidence["window_count"] == 0
    assert evidence["window_visibility_status"] == "running_without_visible_windows"
    assert evidence["window_visibility_limited"] is True
    assert evidence["ui_element_count"] == 2
    assert evidence["ui_unclassified_count"] == 0
    assert evidence["ui_inspection_level"] == "menu"
    assert evidence["ui_visibility_status"] == "menu_level_only"
    assert evidence["ui_visibility_limited"] is True
    assert evidence["menu_level_count"] == 2
    assert evidence["control_like_count"] == 0
    assert evidence["deepest_ui_depth"] == 1
    assert evidence["checks"]["default_app_control_surface_visible"] is True
    assert evidence["checks"]["open_alias_used"] is True
    assert evidence["checks"]["windows_alias_used"] is True
    assert evidence["checks"]["focus_alias_used"] is True
    assert evidence["checks"]["read_ui_alias_used"] is True
    assert evidence["checks"]["verify_alias_used"] is True
    assert evidence["checks"]["verify_returned"] is True
    assert evidence["checks"]["named_ui_elements_match_app"] is True
    assert evidence["checks"]["menu_level_ui_visible"] is True
    assert evidence["cleanup"]["attempted"] is True


def test_real_desktop_ui_inspection_requires_default_app_body_controls():
    assert smoke._default_app_control_surface_visible(
        "Calculator",
        role_counts={"AXButton": 19, "AXMenuItem": 40},
        deepest_ui_depth=5,
    ) is False
    assert smoke._default_app_control_surface_visible(
        "Calculator",
        role_counts={"AXButton": 20},
        deepest_ui_depth=3,
    ) is False
    assert smoke._default_app_control_surface_visible(
        "Calculator",
        role_counts={"AXButton": 20},
        deepest_ui_depth=4,
    ) is True
    assert smoke._default_app_control_surface_visible(
        "Oha-Yachiyo",
        role_counts={},
        deepest_ui_depth=1,
    ) is True


def test_real_desktop_ui_inspection_smoke_fails_when_named_ui_is_not_read(monkeypatch):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda *, query="", limit=200: {
            "ok": True,
            "action": "desktop.list_apps",
            "data": {"query": query, "apps": [{"name": "Calculator"}]},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_status",
        lambda app_name: {
            "ok": True,
            "action": "app.status",
            "data": {"app_name": app_name, "running": True, "status": "running"},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "running_apps",
        lambda: {"ok": True, "data": {"apps": [{"name": "Calculator"}]}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "windows",
        lambda app_name="": {"ok": True, "data": {"app_name": app_name, "count": 0}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_focus",
        lambda app_name: {"ok": True, "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "active_window",
        lambda: {"ok": True, "data": {"app_name": "Calculator"}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "ui_elements",
        lambda *, app_name="", role_filter="", limit=80: {
            "ok": False,
            "action": "desktop.ui_elements",
            "data": {"app_name": app_name},
            "error": "accessibility denied",
        },
    )
    _patch_verify(monkeypatch)

    evidence = smoke.run_smoke(app_name="Calculator", cleanup=False)

    assert evidence["ok"] is False
    assert evidence["checks"]["named_ui_elements_ok"] is False
    assert evidence["checks"]["named_ui_elements_nonempty"] is False
    assert evidence["checks"]["cleanup_ok"] is True


def test_real_desktop_ui_inspection_smoke_surfaces_focus_blocker(monkeypatch):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda *, query="", limit=200: {
            "ok": True,
            "action": "desktop.list_apps",
            "data": {"query": query, "apps": [{"name": "Calculator"}]},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_status",
        lambda app_name: {
            "ok": True,
            "action": "app.status",
            "data": {"app_name": app_name, "running": True, "status": "running"},
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "running_apps",
        lambda: {"ok": True, "data": {"apps": [{"name": "Calculator"}]}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "windows",
        lambda app_name="": {
            "ok": True,
            "data": {
                "app_name": app_name,
                "count": 0,
                "visibility_limited": True,
                "window_visibility_status": "running_without_visible_windows",
            },
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_focus",
        lambda app_name: {
            "ok": False,
            "error": "desktop_session_locked",
            "blocking_condition": "desktop_session_locked",
            "data": {"app_name": app_name, "blocking_condition": "desktop_session_locked"},
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
        "active_window",
        lambda: {"ok": True, "data": {"app_name": "Codex"}},
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "ui_elements",
        lambda *, app_name="", role_filter="", limit=80: {
            "ok": True,
            "action": "desktop.ui_elements",
            "data": {
                "app_name": app_name,
                "elements": [{"depth": 0, "role": "AXMenuBar", "name": ""}],
                "role_counts": {"AXMenuBar": 1},
                "menu_level_count": 1,
                "inspection_level": "menu",
                "visibility_status": "menu_level_only",
                "visibility_limited": True,
            },
        },
    )
    _patch_verify(monkeypatch)

    evidence = smoke.run_smoke(app_name="Calculator", cleanup=False)

    assert evidence["ok"] is False
    assert evidence["error"] == "desktop_session_locked"
    assert evidence["blocking_condition"] == "desktop_session_locked"
    assert evidence["blocking_conditions"] == ["desktop_session_locked"]
    assert evidence["recovery_hints"] == ["Unlock the active macOS user session, then retry."]
    assert evidence["recovery_actions"][0]["tool"] == "app.focus"
    assert evidence["checks"]["focus_tool_returned"] is False


def test_real_desktop_ui_inspection_smoke_cli_outputs_json(monkeypatch, capsys):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    assert smoke.main(["--app-name", "Calculator"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "real_desktop_ui_inspection_smoke"
    assert output["skipped"] is True


def test_real_desktop_ui_inspection_smoke_cli_writes_report_json(
    monkeypatch,
    tmp_path,
    capsys,
):
    report_path = tmp_path / "real-desktop-ui-inspection.json"
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    assert (
        smoke.main(["--app-name", "Calculator", "--report-json", str(report_path)])
        == 0
    )

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output != report
    assert output == {
        "ok": True,
        "mode": "real_desktop_ui_inspection_smoke",
        "skipped": True,
        "platform": "Linux",
        "app_name": "Calculator",
        "report_json": str(report_path),
    }
    assert report["ok"] is True
    assert report["mode"] == "real_desktop_ui_inspection_smoke"
    assert report["skipped"] is True
    assert "real desktop UI inspection smoke report:" in captured.err
    assert str(report_path) in captured.err


def test_real_desktop_ui_inspection_report_stdout_is_compact_on_blocker(
    monkeypatch,
    tmp_path,
    capsys,
):
    report_path = tmp_path / "real-desktop-ui-inspection.json"

    monkeypatch.setattr(
        smoke,
        "run_smoke",
        lambda **kwargs: {
            "ok": False,
            "mode": "real_desktop_ui_inspection_smoke",
            "skipped": False,
            "platform": "Darwin",
            "app_name": kwargs["app_name"],
            "tool_chain": ["desktop.active_window"],
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
            "ui_elements": {"data": {"elements": [{"name": "not for stdout"}]}},
        },
    )

    assert (
        smoke.main(
            [
                "--app-name",
                "Calculator",
                "--report-json",
                str(report_path),
            ]
        )
        == 1
    )

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output["ok"] is False
    assert output["stage"] == "session_preflight"
    assert output["blocking_condition"] == "desktop_session_locked"
    assert output["recommended_tools"] == ["desktop.active_window"]
    assert output["checks"] == {"desktop_session_ready": False}
    assert "preflight" not in output
    assert "ui_elements" not in output
    assert report["preflight"]["data"]["large"] == ["not for stdout"]
    assert report["ui_elements"]["data"]["elements"] == [{"name": "not for stdout"}]
