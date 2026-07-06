"""Tests for the local isolated desktop provider session manager."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from apps.shell.yachiyo_agent import isolated_provider_session as session_module
from apps.shell.yachiyo_agent.isolated_provider_session import (
    IsolatedDesktopProviderSessionManager,
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
