from __future__ import annotations

import json

from scripts import smoke_real_desktop_discovery as smoke


def test_real_desktop_discovery_smoke_skips_non_macos(monkeypatch):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    evidence = smoke.run_smoke()

    assert evidence == {
        "ok": True,
        "mode": "real_desktop_discovery_smoke",
        "skipped": True,
        "platform": "Linux",
        "reason": "real desktop discovery smoke only runs on macOS",
        "cases": [],
    }


def test_real_desktop_discovery_smoke_covers_macos_app_discovery(monkeypatch):
    results = {
        "": {
            "ok": True,
            "action": "desktop.list_apps",
            "summary": "Installed apps: Safari, TextEdit",
            "data": {
                "query": "",
                "apps": [{"name": "Safari"}, {"name": "TextEdit"}],
                "total_count": 2,
            },
            "permission_error": False,
        },
        "Safari": {
            "ok": True,
            "action": "desktop.list_apps",
            "summary": "Installed apps matching Safari: Safari",
            "data": {"query": "Safari", "apps": [{"name": "Safari"}]},
            "permission_error": False,
        },
        "System Settings": {
            "ok": True,
            "action": "desktop.list_apps",
            "summary": "Installed apps matching System Settings: System Settings",
            "data": {"query": "System Settings", "apps": [{"name": "System Settings"}]},
            "permission_error": False,
        },
        "TextEdit": {
            "ok": True,
            "action": "desktop.list_apps",
            "summary": "Installed apps matching TextEdit: TextEdit",
            "data": {"query": "TextEdit", "apps": [{"name": "TextEdit"}]},
            "permission_error": False,
        },
    }

    def fake_list_apps(*, query="", limit=200):
        assert limit in {10, 20}
        return results[query]

    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(smoke.desktop_tools, "list_apps", fake_list_apps)
    monkeypatch.setattr(
        smoke.desktop_tools,
        "permission_preflight",
        lambda: {
            "ok": True,
            "summary": "Desktop execution permissions are ready.",
            "data": {
                "ready": True,
                "permission_targets": [],
                "affected_tools": [],
                "diagnostic_route": "/yachiyo/readiness",
            },
        },
    )

    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert evidence["skipped"] is False
    assert evidence["platform"] == "Darwin"
    assert evidence["catalog"]["total_count"] == 2
    assert evidence["case_count"] == 3
    assert {case["id"] for case in evidence["cases"]} == {
        "safari",
        "system_settings",
        "textedit",
    }
    assert all(case["checks"]["did_not_open_app"] for case in evidence["cases"])
    assert evidence["permission_preflight"]["diagnostic_route"] == "/yachiyo/readiness"


def test_real_desktop_discovery_smoke_cli_outputs_json(monkeypatch, capsys):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    assert smoke.main([]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "real_desktop_discovery_smoke"
    assert output["skipped"] is True


def test_real_desktop_discovery_smoke_cli_writes_report_json(
    monkeypatch,
    tmp_path,
    capsys,
):
    report_path = tmp_path / "real-desktop-discovery.json"
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    assert smoke.main(["--report-json", str(report_path)]) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output == report
    assert report["ok"] is True
    assert report["mode"] == "real_desktop_discovery_smoke"
    assert report["skipped"] is True
    assert "real desktop discovery smoke report:" in captured.err
    assert str(report_path) in captured.err
