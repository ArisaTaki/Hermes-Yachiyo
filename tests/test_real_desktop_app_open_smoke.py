from __future__ import annotations

import json

from scripts import smoke_real_desktop_app_open as smoke


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

    evidence = smoke.run_smoke(app_name="Calculator", cleanup=False)

    assert evidence["ok"] is True
    assert evidence["skipped"] is False
    assert evidence["discovered_app_name"] == "Calculator"
    assert evidence["opened_app_name"] == "Calculator"
    assert evidence["checks"]["discovered_app"] is True
    assert evidence["checks"]["open_ok"] is True
    assert evidence["checks"]["after_status_running"] is True
    assert evidence["cleanup"]["attempted"] is False
    assert calls == [
        ("status", "Calculator"),
        ("open", "Calculator"),
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
