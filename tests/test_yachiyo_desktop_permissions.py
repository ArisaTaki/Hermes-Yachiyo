"""Desktop execution permission readiness tests."""

from __future__ import annotations

import pytest

from apps.shell.yachiyo_agent import desktop_permissions as desktop_permissions_mod


@pytest.fixture(autouse=True)
def clear_permission_probe_cache():
    desktop_permissions_mod.clear_desktop_permission_probe_cache()
    yield
    desktop_permissions_mod.clear_desktop_permission_probe_cache()


def test_desktop_permission_probe_marks_non_macos_unsupported() -> None:
    assert desktop_permissions_mod.desktop_permission_missing_by_capability(
        platform_name="Linux",
        use_cache=False,
    ) == {"desktop_execution": ["unsupported_platform"]}


def test_desktop_permission_probe_aggregates_macos_permission_gaps(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop_permissions_mod,
        "_check_screen_capture_permission",
        lambda: {"ok": False, "allowed": False, "permission_denied": True},
    )
    monkeypatch.setattr(desktop_permissions_mod, "_command_exists", lambda _command: True)
    monkeypatch.setattr(desktop_permissions_mod, "_configured_browser_cdp_url", lambda: "")

    def fake_osascript(script: str, *, timeout: float = 3.0) -> tuple[bool, str]:
        if "first application process" in script:
            return False, "not authorized to send Apple events to System Events"
        if 'id of application "Finder"' in script:
            return True, "com.apple.finder"
        if 'tell application "Finder"' in script:
            return True, "Finder"
        if 'id of application "Music"' in script:
            return False, "application Music was not found"
        if "UI elements enabled" in script:
            return True, "false"
        raise AssertionError(script)

    monkeypatch.setattr(desktop_permissions_mod, "_run_osascript", fake_osascript)

    missing = desktop_permissions_mod.desktop_permission_missing_by_capability(
        platform_name="Darwin",
        use_cache=False,
    )

    assert missing == {
        "screen_capture": ["screen_recording"],
        "active_window": ["automation_or_accessibility"],
        "media_control": ["music_app"],
        "foreground_input": ["accessibility"],
        "browser_control": ["chrome_cdp"],
    }


def test_desktop_permission_probe_marks_music_automation_gap(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop_permissions_mod,
        "_check_screen_capture_permission",
        lambda: {"ok": True, "allowed": True},
    )
    monkeypatch.setattr(desktop_permissions_mod, "_command_exists", lambda _command: True)
    monkeypatch.setattr(desktop_permissions_mod, "_configured_browser_cdp_url", lambda: "http://127.0.0.1:9222")
    monkeypatch.setattr(desktop_permissions_mod, "_browser_cdp_reachable", lambda _url: True)

    def fake_osascript(script: str, *, timeout: float = 3.0) -> tuple[bool, str]:
        if "first application process" in script:
            return True, "Finder"
        if 'id of application "Finder"' in script:
            return True, "com.apple.finder"
        if 'tell application "Finder"' in script:
            return True, "Finder"
        if 'id of application "Music"' in script:
            return True, "com.apple.Music"
        if 'tell application "Music"' in script:
            return False, "Not authorized to send Apple events to Music"
        if "UI elements enabled" in script:
            return True, "true"
        raise AssertionError(script)

    monkeypatch.setattr(desktop_permissions_mod, "_run_osascript", fake_osascript)

    assert desktop_permissions_mod.desktop_permission_missing_by_capability(
        platform_name="Darwin",
        use_cache=False,
    ) == {"media_control": ["automation"]}


def test_desktop_permission_probe_keeps_browser_available_when_cdp_is_reachable(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop_permissions_mod,
        "_check_screen_capture_permission",
        lambda: {"ok": True, "allowed": True},
    )
    monkeypatch.setattr(desktop_permissions_mod, "_command_exists", lambda _command: True)
    monkeypatch.setattr(desktop_permissions_mod, "_run_osascript", lambda *_args, **_kwargs: (True, "true"))
    monkeypatch.setattr(desktop_permissions_mod, "_configured_browser_cdp_url", lambda: "http://127.0.0.1:9222")
    monkeypatch.setattr(desktop_permissions_mod, "_browser_cdp_reachable", lambda _url: True)

    assert desktop_permissions_mod.desktop_permission_missing_by_capability(
        platform_name="Darwin",
        use_cache=False,
    ) == {}


def test_desktop_permission_probe_uses_cached_copies(monkeypatch) -> None:
    calls = {"screen": 0}

    def fake_screen_capture() -> dict[str, object]:
        calls["screen"] += 1
        return {"ok": True, "allowed": True}

    monkeypatch.setattr(desktop_permissions_mod, "_check_screen_capture_permission", fake_screen_capture)
    monkeypatch.setattr(desktop_permissions_mod, "_command_exists", lambda _command: True)
    monkeypatch.setattr(desktop_permissions_mod, "_run_osascript", lambda *_args, **_kwargs: (True, "true"))
    monkeypatch.setattr(desktop_permissions_mod, "_configured_browser_cdp_url", lambda: "")

    first = desktop_permissions_mod.desktop_permission_missing_by_capability(platform_name="Darwin")
    second = desktop_permissions_mod.desktop_permission_missing_by_capability(platform_name="Darwin")

    assert calls["screen"] == 1
    assert first == second == {"browser_control": ["chrome_cdp"]}

    first["browser_control"].append("mutated")
    third = desktop_permissions_mod.desktop_permission_missing_by_capability(platform_name="Darwin")

    assert third == {"browser_control": ["chrome_cdp"]}
