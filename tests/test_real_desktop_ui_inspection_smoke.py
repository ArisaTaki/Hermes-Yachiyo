from __future__ import annotations

import json

from scripts import smoke_real_desktop_ui_inspection as smoke


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


def test_real_desktop_ui_inspection_smoke_reads_named_app_ui(monkeypatch):
    calls: list[tuple[str, str]] = []
    status_values = iter([False, True, False])

    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda *, query="", limit=200: {
            "ok": True,
            "action": "desktop.list_apps",
            "data": {"query": query, "apps": [{"name": "Calculator"}]},
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
            "data": {"apps": [{"name": "Calculator", "frontmost": False}]},
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
            {"role": "AXMenuBar", "name": "Calculator"},
            {"role": "AXMenuBarItem", "name": "File"},
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
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda app_name: {
            "ok": True,
            "action": "app.quit",
            "data": {"app_name": app_name, "quit_verified": True, "running": False},
        },
    )

    evidence = smoke.run_smoke(app_name="Calculator", cleanup=True)

    assert evidence["ok"] is True
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
    assert evidence["checks"]["named_ui_elements_match_app"] is True
    assert evidence["checks"]["menu_level_ui_visible"] is True
    assert evidence["cleanup"]["attempted"] is True


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

    evidence = smoke.run_smoke(app_name="Calculator", cleanup=False)

    assert evidence["ok"] is False
    assert evidence["checks"]["named_ui_elements_ok"] is False
    assert evidence["checks"]["named_ui_elements_nonempty"] is False
    assert evidence["checks"]["cleanup_ok"] is True


def test_real_desktop_ui_inspection_smoke_cli_outputs_json(monkeypatch, capsys):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    assert smoke.main(["--app-name", "Calculator"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "real_desktop_ui_inspection_smoke"
    assert output["skipped"] is True
