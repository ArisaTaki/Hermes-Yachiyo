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
                "focus_verified": bool(focus),
                "window_count": 1 if focus else 0,
                "ui_element_count": 1,
                "control_like_count": 1 if focus else 0,
                "ready_for_foreground_action": bool(focus),
                "checks": {
                    "status_running": True,
                    "focus_verified": bool(focus),
                    "ready_for_foreground_action": bool(focus),
                },
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


def test_real_desktop_app_open_smoke_uses_capability_query_candidate(monkeypatch):
    calls: list[tuple[str, str]] = []
    list_queries: list[tuple[str, int]] = []

    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")

    def fake_list_apps(*, query="", limit=200):
        list_queries.append((query, limit))
        return {
            "ok": True,
            "action": "desktop.list_apps",
            "summary": "Installed apps matching browser: Safari",
            "data": {
                "query": query,
                "apps": [
                    {
                        "name": "Safari",
                        "path": "/Applications/Safari.app",
                        "matched_capability": "web_browser",
                    }
                ],
            },
            "permission_error": False,
        }

    def fake_status(app_name):
        calls.append(("status", app_name))
        return {
            "ok": True,
            "action": "app.status",
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

    monkeypatch.setattr(smoke.desktop_tools, "list_apps", fake_list_apps)
    monkeypatch.setattr(smoke.desktop_tools, "app_status", fake_status)
    monkeypatch.setattr(smoke.desktop_tools, "app_open", fake_open)
    _patch_verify(monkeypatch, calls)

    evidence = smoke.run_smoke(
        app_name="Calculator",
        capability_query="browser",
        cleanup=False,
    )

    assert evidence["ok"] is True
    assert evidence["discovery_query"] == "browser"
    assert evidence["selection_source"] == "capability_query"
    assert evidence["capability_query"] == "browser"
    assert evidence["discovered_app_name"] == "Safari"
    assert evidence["opened_app_name"] == "Safari"
    assert evidence["matched_capability"] == "web_browser"
    assert evidence["selected_candidate"]["name"] == "Safari"
    assert evidence["selected_candidate"]["matched_capability"] == "web_browser"
    assert evidence["checks"]["selected_discovered_app"] is True
    assert evidence["checks"]["capability_match_recorded"] is True
    assert list_queries == [("browser", 10)]
    assert calls == [
        ("status", "Safari"),
        ("open", "Safari"),
        ("verify", "Safari"),
        ("status", "Safari"),
    ]


def test_real_desktop_app_open_smoke_capability_query_without_candidate_does_not_open(
    monkeypatch,
):
    opened: list[str] = []

    monkeypatch.setattr(smoke.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        smoke.desktop_tools,
        "list_apps",
        lambda *, query="", limit=200: {
            "ok": True,
            "action": "desktop.list_apps",
            "data": {"query": query, "apps": []},
            "permission_error": False,
        },
    )

    def fake_open(app_name):
        opened.append(app_name)
        return {
            "ok": True,
            "action": "app.open",
            "data": {"app_name": app_name},
        }

    monkeypatch.setattr(smoke.desktop_tools, "app_open", fake_open)

    evidence = smoke.run_smoke(
        app_name="Calculator",
        capability_query="browser",
        cleanup=False,
    )

    assert evidence["ok"] is False
    assert evidence["tool_chain"] == ["desktop.list_apps"]
    assert evidence["selection_source"] == "capability_query"
    assert evidence["capability_query"] == "browser"
    assert evidence["opened_app_name"] == ""
    assert evidence["error"] == "capability_app_not_found"
    assert evidence["checks"] == {
        "discovered_app": False,
        "selected_discovered_app": False,
        "capability_match_recorded": False,
    }
    assert opened == []


def test_real_desktop_app_open_smoke_can_require_foreground_readiness(
    monkeypatch,
):
    calls: list[tuple[str, str, bool]] = []

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

    def fake_inspect_app(
        app_name,
        *,
        open_if_needed=True,
        focus=True,
        role_filter="",
        limit=80,
    ):
        calls.append(("inspect", app_name, bool(focus)))
        ready = bool(focus)
        return {
            "ok": True,
            "action": "desktop.inspect_app",
            "summary": (
                f"{app_name} is ready"
                if ready
                else f"{app_name} is only running"
            ),
            "data": {
                "app_name": app_name,
                "open_if_needed": open_if_needed,
                "focus_requested": focus,
                "running": True,
                "focus_verified": ready,
                "visibility_limited": not ready,
                "window_count": 1 if ready else 0,
                "ui_element_count": 1,
                "control_like_count": 1 if ready else 0,
                "ready_for_foreground_action": ready,
                "checks": {
                    "status_running": True,
                    "focus_verified": ready,
                    "ready_for_foreground_action": ready,
                },
            },
        }

    monkeypatch.setattr(smoke.desktop_tools, "inspect_app", fake_inspect_app)
    monkeypatch.setattr(
        smoke.desktop_tools,
        "app_show",
        lambda app_name: (_ for _ in ()).throw(
            AssertionError("foreground recovery should not run")
        ),
    )

    evidence = smoke.run_smoke(
        app_name="Calculator",
        require_foreground_ready=True,
        cleanup=False,
    )

    assert evidence["ok"] is True
    assert evidence["tool_chain"] == [
        "desktop.list_apps",
        "desktop.open_app",
        "desktop.verify",
        "desktop.inspect_app",
        "app.status",
    ]
    assert evidence["checks"]["foreground_ready_when_required"] is True
    assert evidence["foreground_readiness"]["required"] is True
    assert evidence["foreground_readiness"]["verify"]["ready"] is False
    assert evidence["foreground_readiness"]["inspect"]["ready"] is True
    assert evidence["foreground_readiness"]["final"]["ready"] is True
    assert "recovery" not in evidence["foreground_readiness"]
    assert calls == [
        ("inspect", "Calculator", False),
        ("inspect", "Calculator", True),
    ]


def test_real_desktop_app_open_smoke_recovers_foreground_readiness(monkeypatch):
    calls: list[tuple[str, str]] = []
    shown = False

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

    def fake_inspect_app(
        app_name,
        *,
        open_if_needed=True,
        focus=True,
        role_filter="",
        limit=80,
    ):
        ready = bool(focus and shown)
        calls.append(("inspect_ready" if ready else "inspect_limited", app_name))
        return {
            "ok": True,
            "action": "desktop.inspect_app",
            "summary": (
                f"{app_name} is ready"
                if ready
                else f"{app_name} has limited visibility"
            ),
            "data": {
                "app_name": app_name,
                "open_if_needed": open_if_needed,
                "focus_requested": focus,
                "running": True,
                "focus_verified": ready,
                "visibility_limited": not ready,
                "window_count": 1 if ready else 0,
                "ui_element_count": 1,
                "control_like_count": 1 if ready else 0,
                "ready_for_foreground_action": ready,
                "checks": {
                    "status_running": True,
                    "focus_verified": ready,
                    "ready_for_foreground_action": ready,
                },
            },
            "recommended_tools": ["app.show"],
            "recovery_actions": [
                {
                    "label": "Show Calculator",
                    "tool": "app.show",
                    "input": {"app_name": app_name},
                    "risk_level": "low",
                }
            ],
        }

    def fake_app_show(app_name):
        nonlocal shown
        shown = True
        calls.append(("show", app_name))
        return {
            "ok": True,
            "action": "app.show",
            "summary": f"Showed {app_name}",
            "data": {"app_name": app_name},
        }

    monkeypatch.setattr(smoke.desktop_tools, "inspect_app", fake_inspect_app)
    monkeypatch.setattr(smoke.desktop_tools, "app_show", fake_app_show)

    evidence = smoke.run_smoke(
        app_name="Calculator",
        require_foreground_ready=True,
        cleanup=False,
    )

    assert evidence["ok"] is True
    assert evidence["tool_chain"] == [
        "desktop.list_apps",
        "desktop.open_app",
        "desktop.verify",
        "desktop.inspect_app",
        "app.show",
        "desktop.inspect_app",
        "app.status",
    ]
    assert evidence["checks"]["foreground_ready_when_required"] is True
    assert evidence["foreground_readiness"]["inspect"]["ready"] is False
    assert evidence["foreground_readiness"]["recovery"] == {
        "tool": "app.show",
        "ok": True,
        "summary": "Showed Calculator",
    }
    assert evidence["foreground_readiness"]["reinspect"]["ready"] is True
    assert evidence["foreground_readiness"]["final"]["ready"] is True
    assert calls == [
        ("inspect_limited", "Calculator"),
        ("inspect_limited", "Calculator"),
        ("show", "Calculator"),
        ("inspect_ready", "Calculator"),
    ]


def test_real_desktop_app_open_smoke_surfaces_nested_focus_blocker(monkeypatch):
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

    def fake_inspect_app(
        app_name,
        *,
        open_if_needed=True,
        focus=True,
        role_filter="",
        limit=80,
    ):
        return {
            "ok": True,
            "action": "desktop.inspect_app",
            "summary": f"{app_name} is not foreground-ready",
            "data": {
                "app_name": app_name,
                "open_if_needed": open_if_needed,
                "focus_requested": focus,
                "running": True,
                "focus_verified": False,
                "visibility_limited": True,
                "window_count": 0,
                "ui_element_count": 1,
                "control_like_count": 0,
                "ready_for_foreground_action": False,
                "checks": {
                    "status_running": True,
                    "focus_verified": False,
                    "ready_for_foreground_action": False,
                },
                "focus_result": {
                    "ok": False,
                    "action": "app.focus",
                    "error": "desktop_session_locked",
                    "blocking_condition": "desktop_session_locked",
                    "recovery_hints": ["Unlock the active macOS user session."],
                    "recovery_actions": [
                        {
                            "label": "Retry focus",
                            "tool": "app.focus",
                            "input": {"app_name": app_name},
                            "risk_level": "low",
                        }
                    ],
                    "data": {"app_name": app_name},
                },
            },
        }

    monkeypatch.setattr(smoke.desktop_tools, "inspect_app", fake_inspect_app)

    evidence = smoke.run_smoke(
        app_name="Calculator",
        require_foreground_ready=True,
        recover_foreground=False,
        cleanup=False,
    )

    assert evidence["ok"] is False
    assert evidence["blocking_condition"] == "desktop_session_locked"
    assert evidence["blocking_conditions"] == ["desktop_session_locked"]
    assert evidence["recovery_hints"] == ["Unlock the active macOS user session."]
    assert evidence["foreground_readiness"]["final"]["blocking_condition"] == (
        "desktop_session_locked"
    )
    assert evidence["checks"]["foreground_ready_when_required"] is False


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


def test_real_desktop_app_open_smoke_cli_outputs_capability_query(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(smoke.platform, "system", lambda: "Linux")

    assert (
        smoke.main(
            [
                "--app-name",
                "Calculator",
                "--capability-query",
                "browser",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["skipped"] is True
    assert output["app_name"] == "Calculator"
    assert output["capability_query"] == "browser"


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
    assert output != report
    assert output == {
        "ok": True,
        "mode": "real_desktop_app_open_smoke",
        "skipped": True,
        "platform": "Linux",
        "app_name": "Calculator",
        "report_json": str(report_path),
    }
    assert report["ok"] is True
    assert report["mode"] == "real_desktop_app_open_smoke"
    assert report["skipped"] is True
    assert report["app_name"] == "Calculator"
    assert "real desktop app open smoke report:" in captured.err
    assert str(report_path) in captured.err


def test_real_desktop_app_open_smoke_report_stdout_is_compact_on_blocker(
    monkeypatch,
    tmp_path,
    capsys,
):
    report_path = tmp_path / "real-desktop-app-open.json"

    monkeypatch.setattr(
        smoke,
        "run_smoke",
        lambda **kwargs: {
            "ok": False,
            "mode": "real_desktop_app_open_smoke",
            "skipped": False,
            "platform": "Darwin",
            "app_name": kwargs["app_name"],
            "discovered_app_name": "Calculator",
            "opened_app_name": "Calculator",
            "tool_chain": ["desktop.list_apps", "desktop.open_app", "desktop.verify"],
            "case_count": 1,
            "error": "desktop_session_locked",
            "blocking_condition": "desktop_session_locked",
            "checks": {
                "open_ok": True,
                "foreground_ready_when_required": False,
            },
            "foreground_readiness": {
                "required": True,
                "final": {
                    "ready": False,
                    "summary": "foreground action is not ready",
                    "blocking_condition": "desktop_session_locked",
                },
            },
            "open_result": {"data": {"large": ["not for stdout"]}},
            "verify_result": {"data": {"elements": [{"name": "not for stdout"}]}},
        },
    )

    assert (
        smoke.main(
            [
                "--app-name",
                "Calculator",
                "--require-foreground-ready",
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
    assert output["blocking_condition"] == "desktop_session_locked"
    assert output["foreground_readiness"] == {
        "required": True,
        "ready": False,
        "summary": "foreground action is not ready",
        "blocking_condition": "desktop_session_locked",
    }
    assert "open_result" not in output
    assert "verify_result" not in output
    assert report["open_result"]["data"]["large"] == ["not for stdout"]
    assert report["verify_result"]["data"]["elements"] == [{"name": "not for stdout"}]
