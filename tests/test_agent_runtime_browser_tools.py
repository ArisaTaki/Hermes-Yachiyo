"""Browser/CDP structured tool tests."""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

from apps.shell.agent.tools import browser as browser_mod
from apps.shell.agent.tools.broker import ToolBroker


def _broker(tmp_path):
    return ToolBroker(
        {"default_workdir": str(tmp_path), "readable_scopes": ["."], "writable_scopes": ["."]},
        tmp_path / "artifacts",
    )


def test_browser_open_url_uses_configured_cdp(monkeypatch) -> None:
    monkeypatch.setattr(browser_mod, "_configured_browser_cdp_url", lambda: "http://127.0.0.1:9222")
    monkeypatch.setattr(
        browser_mod,
        "_cdp_new_page",
        lambda cdp_url, url: {
            "id": "target-1",
            "type": "page",
            "title": "Example",
            "url": url,
            "cdp_url": cdp_url,
        },
    )

    result = browser_mod.open_url("https://example.com/demo")

    assert result["ok"] is True
    assert result["fallback_used"] is False
    assert result["data"]["target_id"] == "target-1"
    assert result["data"]["url"] == "https://example.com/demo"


def test_browser_open_url_falls_back_to_system_browser_without_cdp(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(browser_mod, "_configured_browser_cdp_url", lambda: "")
    monkeypatch.setattr(browser_mod.sys, "platform", "darwin")
    monkeypatch.setattr(browser_mod.subprocess, "run", fake_run)

    result = browser_mod.open_url("https://example.com/fallback")

    assert result["ok"] is True
    assert result["fallback_used"] is True
    assert result["fallback"] == "system_browser"
    assert calls[0][0] == ["open", "https://example.com/fallback"]


def test_browser_cdp_unavailable_returns_recovery_target(monkeypatch) -> None:
    monkeypatch.setattr(browser_mod, "_configured_browser_cdp_url", lambda: "")
    monkeypatch.setattr(browser_mod.sys, "platform", "linux")

    result = browser_mod.open_url("https://example.com/no-cdp")

    assert result["ok"] is False
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["chrome_cdp"]
    assert result["permission_targets"] == ["chrome_cdp"]


def test_browser_extract_text_uses_current_page_evaluation(monkeypatch) -> None:
    monkeypatch.setattr(
        browser_mod,
        "_evaluate_current_page",
        lambda _expression: {"ok": True, "text": "Hello from browser"},
    )

    result = browser_mod.extract_text("#main")

    assert result["ok"] is True
    assert result["data"] == {
        "selector": "#main",
        "text": "Hello from browser",
        "truncated": False,
    }


def test_browser_screenshot_tool_writes_artifact_metadata(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    png_bytes = b"browser-png"

    monkeypatch.setattr(
        browser_mod,
        "_page_websocket_url",
        lambda: "ws://127.0.0.1/devtools/page/1",
    )
    monkeypatch.setattr(
        browser_mod,
        "_cdp_command",
        lambda _url, method, params: (
            {"data": base64.b64encode(png_bytes).decode("ascii")}
            if method == "Page.captureScreenshot" and params["format"] == "png"
            else {}
        ),
    )

    result = broker.call("browser.screenshot", {"reason": "capture page"})

    assert result["ok"] is True
    assert result["reason"] == "capture page"
    assert result["artifact"] == {
        "path": "browser/current-page.png",
        "kind": "image",
        "mime_type": "image/png",
        "size_bytes": len(png_bytes),
    }
    assert (tmp_path / "artifacts" / "browser" / "current-page.png").read_bytes() == png_bytes


def test_browser_screenshot_falls_back_to_screen_capture_artifact(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    fallback_bytes = b"fallback-browser-png"

    def raise_no_cdp() -> str:
        raise RuntimeError("browser.cdp_url is not configured")

    def fake_capture_screen(target_path) -> dict[str, object]:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fallback_bytes)
        return {
            "path": str(target),
            "mime_type": "image/png",
            "format": "png",
            "width": 32,
            "height": 24,
            "size": len(fallback_bytes),
        }

    monkeypatch.setattr(browser_mod, "_page_websocket_url", raise_no_cdp)
    monkeypatch.setattr(browser_mod, "_capture_screen_fallback", fake_capture_screen)

    result = broker.call("browser.screenshot", {"reason": "capture fallback page"})

    assert result["ok"] is True
    assert result["fallback_used"] is True
    assert result["fallback"] == "screen.capture"
    assert result["missing_permissions"] == ["chrome_cdp"]
    assert result["permission_targets"] == ["chrome_cdp"]
    assert result["reason"] == "capture fallback page"
    assert result["artifact"] == {
        "path": "browser/current-page.png",
        "kind": "image",
        "mime_type": "image/png",
        "size_bytes": len(fallback_bytes),
    }
    assert result["data"]["path"] == "browser/current-page.png"
    assert result["data"]["width"] == 32
    assert (
        tmp_path / "artifacts" / "browser" / "current-page.png"
    ).read_bytes() == fallback_bytes


def test_browser_screenshot_reports_screen_capture_permission_when_fallback_denied(
    tmp_path,
    monkeypatch,
) -> None:
    def raise_no_cdp() -> str:
        raise RuntimeError("No debuggable browser page found")

    def raise_screen_permission(_target_path) -> dict[str, object]:
        raise RuntimeError("screen recording not authorized")

    monkeypatch.setattr(browser_mod, "_page_websocket_url", raise_no_cdp)
    monkeypatch.setattr(browser_mod, "_capture_screen_fallback", raise_screen_permission)

    result = browser_mod.screenshot(tmp_path / "page.png")

    assert result["ok"] is False
    assert result["error"] == "browser_screenshot_unavailable"
    assert result["permission_error"] is True
    assert result["fallback_used"] is True
    assert result["fallback"] == "screen.capture"
    assert result["missing_permissions"] == ["chrome_cdp", "screen_recording"]
    assert result["permission_targets"] == ["chrome_cdp", "screen_recording"]
