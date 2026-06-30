from __future__ import annotations

import json

from scripts import smoke_real_desktop_app_open as smoke


def _patch_verify(monkeypatch, calls: list[tuple[str, str]] | None = None) -> None:
    def fake_inspect_app(
        app_name,
        *,
        open_if_needed=True,
        focus=True,
        role_filter="",
        limit=80,
    ):
        if calls is not None:
            calls.append(("verify", app_name))
        return {
            "ok": True,
            "action": "desktop.inspect_app",
            "summary": f"Verified {app_name}",
            "data": {
                "app_name": app_name,
                "open_if_needed": open_if_needed,
                "focus_requested": focus,
                "running": True,
                "checks": {"status_running": True},
                "ui_element_count": 1,
            },
            "permission_error": False,
        }

    monkeypatch.setattr(smoke.desktop_tools, "inspect_app", fake_inspect_app)


def test_real_desktop_app_open_smoke_skips_non_macos(monkeypatch):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    evidence = smoke.run_smoke(app_name="Calculator")

    assert evidence == {
        "ok": True,
        "mode": "real_desktop_app_open_smoke",
        "skipped": True,
        "platform": "Linux",
        "app_name": "Calculator",
        "reason": "real desktop app open smoke only runs on macOS",
    }


def test_real_desktop_app_open_smoke_discovers_opens_and_verifies_app(monkeypatch):
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda *, query="", limit=200: {
            "ok": True,
            "action": "desktop.list_apps",
            "summary": "Installed apps matching Calculator: Calculator",
            "data": {"query": query, "apps": [{"name": "Calculator"}]},
            "permission_error": False,
        },
    )

    def fake_status(app_name):
        calls.append(("status", app_name))
        return {
            "ok": True,
            "action": "app.status",
            "summary": f"{app_name} status",
            "data": {
                "app_name": app_name,
                "running": len(calls) > 1,
                "status": "running" if len(calls) > 1 else "not_running",
            },
            "permission_error": False,
        }

    def fake_open(app_name):
        calls.append(("open", app_name))
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {
                "app_name": app_name,
                "launch_verified": True,
                "launch_status": "running",
            },
            "permission_error": False,
        }

    monkeypatch.setattr(smoke.desktop_tools, "app_status", fake_status)
    monkeypatch.setattr(smoke.desktop_tools, "app_open", fake_open)
    _patch_verify(monkeypatch, calls)

    evidence = smoke.run_smoke(app_name="Calculator", cleanup=False)

    assert evidence["ok"] is True
    assert evidence["skipped"] is False
    assert evidence["tool_chain"] == [
        "desktop.list_apps",
        "desktop.open_app",
        "desktop.verify",
        "app.status",
    ]
    assert evidence["discovered_app_name"] == "Calculator"
    assert evidence["opened_app_name"] == "Calculator"
    assert evidence["case_count"] == 1
    assert evidence["cases"][0]["id"] == "open_discovered_app"
    assert evidence["cases"][0]["app_name"] == "Calculator"
    assert evidence["cases"][0]["tool_chain"] == evidence["tool_chain"]
    assert evidence["cases"][0]["passed"] is True
    assert evidence["planner_alignment"]["intent_category"] == "desktop_app_open"
    assert evidence["planner_alignment"]["execution_pattern"] == [
        "discover",
        "execute",
        "verify",
    ]
    assert evidence["planner_alignment"]["capabilities"] == [
        "desktop.app_discovery",
        "desktop.app_launch",
        "desktop.app_verification",
    ]
    assert evidence["planner_alignment"]["tool_plan"] == [
        {"tool": "desktop.list_apps"},
        {"tool": "desktop.open_app"},
        {"tool": "desktop.verify"},
        {"tool": "app.status"},
    ]
    assert evidence["planner_alignment"]["approval_policy"] == {
        "mutates_desktop": True,
        "approval_required": False,
    }
    assert evidence["checks"]["discovered_app"] is True
    assert evidence["checks"]["open_ok"] is True
    assert evidence["checks"]["open_alias_used"] is True
    assert evidence["checks"]["verify_ok"] is True
    assert evidence["checks"]["verify_alias_used"] is True
    assert evidence["verify_result"]["action"] == "desktop.verify"
    assert evidence["open_result"]["action"] == "desktop.open_app"
    assert evidence["checks"]["after_status_running"] is True
    assert evidence["cleanup"]["attempted"] is False
    assert calls == [
        ("status", "Calculator"),
        ("open", "Calculator"),
        ("verify", "Calculator"),
        ("status", "Calculator"),
    ]


def test_real_desktop_app_open_smoke_cleans_up_app_started_by_smoke(monkeypatch):
    status_values = iter([False, True, False])
    calls: list[tuple[str, str]] = []

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
            "permission_error": False,
        }

    monkeypatch.setattr(smoke.desktop_tools, "app_status", fake_status)
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {
            "ok": True,
            "action": "app.open",
            "data": {
                "app_name": app_name,
                "launch_verified": True,
                "launch_status": "running",
            },
        },
    )
    _patch_verify(monkeypatch)

    def fake_quit(app_name):
        calls.append(("quit", app_name))
        return {
            "ok": True,
            "action": "app.quit",
            "data": {"app_name": app_name, "quit_verified": True, "running": False},
        }

    monkeypatch.setattr(smoke.desktop_tools, "app_quit", fake_quit)

    evidence = smoke.run_smoke(app_name="Calculator", cleanup=True)

    assert evidence["ok"] is True
    assert evidence["cleanup"]["attempted"] is True
    assert evidence["cleanup"]["final_running"] is False
    assert calls == [
        ("status", "Calculator"),
        ("status", "Calculator"),
        ("quit", "Calculator"),
        ("status", "Calculator"),
    ]


def test_real_desktop_app_open_smoke_waits_for_async_quit(monkeypatch):
    status_values = iter([False, True, True, True, False])
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(smoke.time, "sleep", lambda _seconds: None)
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
            "permission_error": False,
        }

    monkeypatch.setattr(smoke.desktop_tools, "app_status", fake_status)
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {
            "ok": True,
            "action": "app.open",
            "data": {
                "app_name": app_name,
                "launch_verified": True,
                "launch_status": "running",
            },
        },
    )
    _patch_verify(monkeypatch)
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda app_name: calls.append(("quit", app_name))
        or {
            "ok": True,
            "action": "app.quit",
            "data": {
                "app_name": app_name,
                "quit_verified": False,
                "running": True,
            },
        },
    )

    evidence = smoke.run_smoke(app_name="Calculator", cleanup=True)

    assert evidence["ok"] is True
    assert evidence["checks"]["cleanup_ok"] is True
    assert evidence["cleanup"]["final_running"] is False
    assert evidence["cleanup"]["status_polls"] == [
        {"attempt": 1, "running": True},
        {"attempt": 2, "running": True},
        {"attempt": 3, "running": False},
    ]
    assert calls == [
        ("status", "Calculator"),
        ("status", "Calculator"),
        ("quit", "Calculator"),
        ("status", "Calculator"),
        ("status", "Calculator"),
        ("status", "Calculator"),
    ]


def test_real_desktop_app_open_smoke_does_not_quit_existing_app(monkeypatch):
    calls: list[str] = []

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
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_status",
        lambda app_name: {
            "ok": True,
            "action": "app.status",
            "data": {"app_name": app_name, "running": True, "status": "running"},
            "permission_error": False,
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {
            "ok": True,
            "action": "app.open",
            "data": {
                "app_name": app_name,
                "launch_verified": True,
                "launch_status": "running",
            },
        },
    )
    _patch_verify(monkeypatch)
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_quit",
        lambda app_name: calls.append(app_name)
        or {"ok": True, "action": "app.quit"},
    )

    evidence = smoke.run_smoke(app_name="Calculator", cleanup=True)

    assert evidence["ok"] is True
    assert evidence["cleanup"] == {
        "requested": True,
        "attempted": False,
        "ok": True,
        "reason": "app was already running before smoke",
    }
    assert evidence["checks"]["did_not_quit_existing_app"] is True
    assert calls == []


def test_real_desktop_app_open_smoke_fails_when_open_does_not_launch(monkeypatch):
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
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_status",
        lambda app_name: {
            "ok": True,
            "action": "app.status",
            "data": {"app_name": app_name, "running": False, "status": "not_running"},
            "permission_error": False,
        },
    )
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_open",
        lambda app_name: {
            "ok": False,
            "action": "app.open",
            "error": "app_not_found",
            "data": {"app_name": app_name},
        },
    )

    evidence = smoke.run_smoke(app_name="Calculator", cleanup=True)

    assert evidence["ok"] is False
    assert evidence["checks"]["open_ok"] is False
    assert evidence["checks"]["after_status_running"] is False


def test_real_desktop_app_open_smoke_cli_outputs_json(monkeypatch, capsys):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    assert smoke.main(["--app-name", "Calculator"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "real_desktop_app_open_smoke"
    assert output["skipped"] is True
    assert output["app_name"] == "Calculator"


def test_real_desktop_app_open_smoke_cli_writes_report_json(
    monkeypatch,
    tmp_path,
    capsys,
):
    report_path = tmp_path / "real-desktop-app-open.json"
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    assert (
        smoke.main(["--app-name", "Calculator", "--report-json", str(report_path)])
        == 0
    )

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output == report
    assert report["ok"] is True
    assert report["mode"] == "real_desktop_app_open_smoke"
    assert report["skipped"] is True
    assert report["app_name"] == "Calculator"
    assert "real desktop app open smoke report:" in captured.err
    assert str(report_path) in captured.err
