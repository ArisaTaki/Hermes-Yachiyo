"""Tests for the local isolated desktop provider session manager."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from apps.shell.yachiyo_agent import isolated_provider_session as session_module
from apps.shell.yachiyo_agent.isolated_provider_session import (
    IsolatedDesktopProviderSessionManager,
    annotate_envelope_with_desktop_provider_session,
    ensure_isolated_desktop_provider_session_for_envelope,
)


def test_isolated_provider_session_manager_starts_applies_env_and_stops(
    monkeypatch,
) -> None:
    for key in session_module._ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    popen_calls: list[list[str]] = []

    class FakeProcess:
        pid = 4242

        def __init__(self) -> None:
            payload = {
                "ok": True,
                "provider_id": "test-isolated",
                "url": "http://127.0.0.1:32109",
                "supported_tools": ["desktop.safe_type_text", "app.open"],
            }
            self.stdout = io.StringIO(json.dumps(payload) + "\n")
            self.stderr = io.StringIO("")
            self.terminated = False

        def poll(self) -> int | None:
            return 0 if self.terminated else None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> int:
            self.terminated = True
            return 0

        def kill(self) -> None:
            self.terminated = True

    def fake_popen(command: list[str], **_: Any) -> FakeProcess:
        popen_calls.append(command)
        return FakeProcess()

    monkeypatch.setattr(session_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        session_module,
        "desktop_execution_provider_status_from_env",
        lambda env, probe_health=False: {
            "configured": bool(env),
            "available": bool(env),
            "status": "ready" if env else "not_configured",
            "probe_health": probe_health,
        },
    )
    manager = IsolatedDesktopProviderSessionManager(repo_root=Path("/repo"))

    started = manager.start(provider_id="test-isolated", tools=["desktop.safe_type_text", "app.open"])

    assert started["started"] is True
    assert started["running"] is True
    assert started["provider_id"] == "test-isolated"
    assert started["url"] == "http://127.0.0.1:32109"
    assert started["provider_status"]["status"] == "ready"
    assert "--provider-id" in popen_calls[0]
    assert session_module.os.environ["OHA_YACHIYO_DESKTOP_PROVIDER_URL"] == (
        "http://127.0.0.1:32109"
    )
    assert session_module.os.environ["OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED"] == "true"

    stopped = manager.stop()

    assert stopped["stopped"] is True
    assert stopped["running"] is False
    assert "OHA_YACHIYO_DESKTOP_PROVIDER_URL" not in session_module.os.environ


def test_ensure_isolated_provider_session_detects_keyboard_mouse_requests(
    monkeypatch,
) -> None:
    starts: list[dict[str, Any] | None] = []

    monkeypatch.setattr(
        session_module,
        "isolated_desktop_provider_session_status",
        lambda: {"ok": True, "status": "stopped", "running": False},
    )
    monkeypatch.setattr(
        session_module,
        "start_isolated_desktop_provider_session",
        lambda request=None: starts.append(request)
        or {
            "ok": True,
            "status": "running",
            "running": True,
            "started": True,
            "provider_id": "local-isolated-desktop",
            "url": "http://127.0.0.1:19093",
            "provider_status": {
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "keyboard_mouse_capture_supported": True,
                "supported_tools": ["desktop.safe_type_text"],
            },
        },
    )
    envelope = {
        "requests": [
            {
                "request_id": "request-type",
                "tool_name": "desktop.safe_type_text",
                "execution_mode": {"keyboard_mouse_capture": True},
                "desktop_execution_route": {
                    "status": "sandbox_keyboard_mouse_provider_required",
                    "blocking_conditions": ["sandbox_keyboard_mouse_provider_required"],
                },
                "sandbox_provider": {"desktop_session_isolated": False},
            }
        ]
    }

    session = ensure_isolated_desktop_provider_session_for_envelope(envelope)
    annotated = annotate_envelope_with_desktop_provider_session(envelope, session)

    assert starts == [{"tools": ["desktop.safe_type_text"]}]
    assert session["needed"] is True
    assert session["running"] is True
    assert session["started"] is True
    assert session["request_ids"] == ["request-type"]
    assert session["tool_names"] == ["desktop.safe_type_text"]
    assert session["desktop_session_kind"] == "isolated_desktop"
    assert session["desktop_session_isolated"] is True
    assert session["foreground_takeover_required"] is False
    assert session["keyboard_mouse_capture_supported"] is True
    assert session["supported_tools"] == ["desktop.safe_type_text"]
    assert annotated["desktop_provider_session"]["provider_id"] == "local-isolated-desktop"
    assert annotated["requests"][0]["desktop_provider_session"]["needed"] is True
    assert annotated["requests"][0]["desktop_provider_session"]["desktop_session_isolated"] is True
    assert (
        annotated["requests"][0]["desktop_provider_session"]["foreground_takeover_required"]
        is False
    )


def test_ensure_isolated_provider_session_scopes_related_desktop_requests(
    monkeypatch,
) -> None:
    starts: list[dict[str, Any] | None] = []

    monkeypatch.setattr(
        session_module,
        "isolated_desktop_provider_session_status",
        lambda: {"ok": True, "status": "stopped", "running": False},
    )
    monkeypatch.setattr(
        session_module,
        "start_isolated_desktop_provider_session",
        lambda request=None: starts.append(request)
        or {
            "ok": True,
            "status": "running",
            "running": True,
            "started": True,
            "provider_id": "local-isolated-desktop",
            "url": "http://127.0.0.1:19093",
            "provider_status": {
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "keyboard_mouse_capture_supported": True,
                "supported_tools": [
                    "app.open",
                    "desktop.safe_type_text",
                    "desktop.verify",
                ],
            },
        },
    )
    envelope = {
        "requests": [
            {
                "request_id": "request-open",
                "tool_name": "app.open",
                "input": {"app_name": "PixelForge"},
            },
            {
                "request_id": "request-type",
                "tool_name": "desktop.safe_type_text",
                "execution_mode": {"keyboard_mouse_capture": True},
                "desktop_execution_route": {
                    "status": "sandbox_keyboard_mouse_provider_required",
                    "blocking_conditions": ["sandbox_keyboard_mouse_provider_required"],
                },
                "sandbox_provider": {"desktop_session_isolated": False},
            },
            {
                "request_id": "request-verify",
                "tool_name": "desktop.verify",
                "input": {"app_name": "PixelForge", "expected_text": "hello"},
            },
            {
                "request_id": "request-data",
                "tool_name": "data.analyze",
            },
        ]
    }

    session = ensure_isolated_desktop_provider_session_for_envelope(envelope)
    annotated = annotate_envelope_with_desktop_provider_session(envelope, session)

    assert starts == [
        {"tools": ["app.open", "desktop.safe_type_text", "desktop.verify"]}
    ]
    assert session["needed"] is True
    assert session["request_ids"] == [
        "request-open",
        "request-type",
        "request-verify",
    ]
    assert session["tool_names"] == [
        "app.open",
        "desktop.safe_type_text",
        "desktop.verify",
    ]
    assert annotated["requests"][0]["desktop_provider_session"]["provider_id"] == (
        "local-isolated-desktop"
    )
    assert annotated["requests"][1]["desktop_provider_session"]["provider_id"] == (
        "local-isolated-desktop"
    )
    assert annotated["requests"][2]["desktop_provider_session"]["provider_id"] == (
        "local-isolated-desktop"
    )
    assert "desktop_provider_session" not in annotated["requests"][3]


def test_ensure_isolated_provider_session_does_not_start_for_media_app_without_sandbox_route(
    monkeypatch,
) -> None:
    starts: list[dict[str, Any] | None] = []

    monkeypatch.setattr(
        session_module,
        "isolated_desktop_provider_session_status",
        lambda: {"ok": True, "status": "stopped", "running": False},
    )
    monkeypatch.setattr(
        session_module,
        "start_isolated_desktop_provider_session",
        lambda request=None: starts.append(request)
        or {
            "ok": True,
            "status": "running",
            "running": True,
            "started": True,
            "provider_id": "local-isolated-desktop",
            "url": "http://127.0.0.1:19093",
            "provider_status": {
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "keyboard_mouse_capture_supported": True,
                "supported_tools": ["media.music_app_open_and_play"],
            },
        },
    )
    envelope = {
        "requests": [
            {
                "request_id": "request-music",
                "tool_name": "media.music_app_open_and_play",
                "input": {"app_name": "Music"},
            }
        ]
    }

    session = ensure_isolated_desktop_provider_session_for_envelope(envelope)
    annotated = annotate_envelope_with_desktop_provider_session(envelope, session)

    assert starts == []
    assert session["needed"] is False
    assert session["running"] is False
    assert session["started"] is False
    assert session["request_ids"] == []
    assert session["tool_names"] == []
    assert "desktop_provider_session" not in annotated["requests"][0]


def test_ensure_isolated_provider_session_does_not_start_for_app_open_without_sandbox_route(
    monkeypatch,
) -> None:
    starts: list[dict[str, Any] | None] = []

    monkeypatch.setattr(
        session_module,
        "isolated_desktop_provider_session_status",
        lambda: {"ok": True, "status": "stopped", "running": False},
    )
    monkeypatch.setattr(
        session_module,
        "start_isolated_desktop_provider_session",
        lambda request=None: starts.append(request)
        or {
            "ok": True,
            "status": "running",
            "running": True,
            "started": True,
            "provider_id": "local-isolated-desktop",
            "url": "http://127.0.0.1:19093",
            "provider_status": {
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "supported_tools": ["app.open"],
            },
        },
    )
    envelope = {
        "requests": [
            {
                "request_id": "request-open",
                "tool_name": "app.open",
                "input": {"app_name": "PixelForge"},
            }
        ]
    }

    session = ensure_isolated_desktop_provider_session_for_envelope(envelope)
    annotated = annotate_envelope_with_desktop_provider_session(envelope, session)

    assert starts == []
    assert session["needed"] is False
    assert session["running"] is False
    assert session["started"] is False
    assert session["request_ids"] == []
    assert session["tool_names"] == []
    assert "desktop_provider_session" not in annotated["requests"][0]


def test_ensure_isolated_provider_session_detects_app_open_with_sandbox_route(
    monkeypatch,
) -> None:
    starts: list[dict[str, Any] | None] = []

    monkeypatch.setattr(
        session_module,
        "isolated_desktop_provider_session_status",
        lambda: {"ok": True, "status": "stopped", "running": False},
    )
    monkeypatch.setattr(
        session_module,
        "start_isolated_desktop_provider_session",
        lambda request=None: starts.append(request)
        or {
            "ok": True,
            "status": "running",
            "running": True,
            "started": True,
            "provider_id": "local-isolated-desktop",
            "url": "http://127.0.0.1:19093",
            "provider_status": {
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "supported_tools": ["app.open"],
            },
        },
    )
    envelope = {
        "requests": [
            {
                "request_id": "request-open",
                "tool_name": "app.open",
                "input": {"app_name": "PixelForge"},
                "desktop_execution_route": {
                    "selected_provider_kind": "sandbox_desktop",
                    "status": "provider_required",
                    "sandbox_required": True,
                    "blocking_conditions": ["sandbox_desktop_provider_required"],
                },
            }
        ]
    }

    session = ensure_isolated_desktop_provider_session_for_envelope(envelope)
    annotated = annotate_envelope_with_desktop_provider_session(envelope, session)

    assert starts == [{"tools": ["app.open"]}]
    assert session["needed"] is True
    assert session["running"] is True
    assert session["started"] is True
    assert session["request_ids"] == ["request-open"]
    assert session["tool_names"] == ["app.open"]
    assert annotated["requests"][0]["desktop_provider_session"]["provider_id"] == (
        "local-isolated-desktop"
    )


def test_ensure_isolated_provider_session_detects_inspect_app_with_sandbox_route(
    monkeypatch,
) -> None:
    starts: list[dict[str, Any] | None] = []

    monkeypatch.setattr(
        session_module,
        "isolated_desktop_provider_session_status",
        lambda: {"ok": True, "status": "stopped", "running": False},
    )
    monkeypatch.setattr(
        session_module,
        "start_isolated_desktop_provider_session",
        lambda request=None: starts.append(request)
        or {
            "ok": True,
            "status": "running",
            "running": True,
            "started": True,
            "provider_id": "local-isolated-desktop",
            "url": "http://127.0.0.1:19093",
            "provider_status": {
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "supported_tools": ["desktop.inspect_app"],
            },
        },
    )
    envelope = {
        "requests": [
            {
                "request_id": "request-inspect",
                "tool_name": "desktop.inspect_app",
                "input": {"app_name": "PixelForge", "open_if_needed": True},
                "desktop_execution_route": {
                    "selected_provider_kind": "sandbox_desktop",
                    "status": "provider_required",
                    "sandbox_required": True,
                    "blocking_conditions": ["sandbox_desktop_provider_required"],
                },
            }
        ]
    }

    session = ensure_isolated_desktop_provider_session_for_envelope(envelope)
    annotated = annotate_envelope_with_desktop_provider_session(envelope, session)

    assert starts == [{"tools": ["desktop.inspect_app"]}]
    assert session["needed"] is True
    assert session["running"] is True
    assert session["started"] is True
    assert session["request_ids"] == ["request-inspect"]
    assert session["tool_names"] == ["desktop.inspect_app"]
    assert annotated["requests"][0]["desktop_provider_session"]["provider_id"] == (
        "local-isolated-desktop"
    )
