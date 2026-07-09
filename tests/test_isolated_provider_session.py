"""Tests for the local isolated desktop provider session manager."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

from apps.shell.agent.runtime.desktop_provider_session_events import (
    desktop_provider_session_event_payload,
)
from apps.shell.yachiyo_agent import isolated_provider_session as session_module
from apps.shell.yachiyo_agent.isolated_provider_session import (
    IsolatedDesktopProviderSessionManager,
    annotate_envelope_with_desktop_provider_session,
    ensure_isolated_desktop_provider_session_for_envelope,
)
from apps.shell.yachiyo_agent.desktop_provider_contract import (
    OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
)


def test_isolated_provider_session_manager_starts_applies_env_and_stops(
    monkeypatch,
) -> None:
    for key in session_module._ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST", raising=False)

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


def test_start_isolated_provider_session_can_start_managed_external_provider(
    monkeypatch,
    tmp_path,
) -> None:
    for key in session_module._ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST", raising=False)
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND",
        "python -m fake_virtual_desktop_provider",
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_START_CWD", str(tmp_path))
    popen_calls: list[dict[str, Any]] = []

    class FakeProcess:
        pid = 5252

        def __init__(self) -> None:
            payload = {
                "ok": True,
                "provider_id": "managed-virtual-desktop",
                "provider_kind": "sandbox_desktop",
                "url": "http://127.0.0.1:29093",
                "status_url": "http://127.0.0.1:29093/status",
                "execute_url": "http://127.0.0.1:29093/tools/execute",
                "supported_tools": ["app.open", "desktop.verify"],
                "keyboard_mouse_capture_supported": True,
                "desktop_session_kind": "virtual_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
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

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        popen_calls.append({"command": command, **kwargs})
        return FakeProcess()

    def fake_provider_status(env=None, probe_health=False):
        clean_env = dict(env or {})
        configured = bool(clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_URL"))
        return {
            "configured": configured,
            "available": configured,
            "adapter_ready": configured,
            "provider_id": clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_ID", ""),
            "endpoint_origin": clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_URL", ""),
            "status": "available" if configured else "not_configured",
            "probe_health": probe_health,
            "desktop_session_kind": clean_env.get(
                "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
                "",
            ),
            "desktop_session_isolated": True if configured else None,
            "foreground_takeover_required": False if configured else None,
            "keyboard_mouse_capture_supported": True if configured else None,
            "desktop_backend_kind": "virtual_desktop_backend" if configured else "",
            "desktop_backend_is_loopback": False if configured else None,
            "desktop_backend_ready_for_public_release": True if configured else None,
            "requires_real_virtual_desktop_backend": False if configured else None,
            "supported_tools": ["app.open", "desktop.verify"] if configured else [],
        }

    monkeypatch.setattr(session_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        session_module,
        "desktop_execution_provider_status_from_env",
        fake_provider_status,
    )

    manager = IsolatedDesktopProviderSessionManager(repo_root=Path("/repo"))
    monkeypatch.setattr(session_module, "_SESSION_MANAGER", manager)

    started = session_module.start_isolated_desktop_provider_session(
        {"tools": ["app.open", "desktop.verify"]}
    )

    assert popen_calls[0]["command"] == [
        "python",
        "-m",
        "fake_virtual_desktop_provider",
    ]
    assert popen_calls[0]["cwd"] == str(tmp_path)
    assert popen_calls[0]["env"]["OHA_YACHIYO_DESKTOP_PROVIDER_REQUESTED_TOOLS"] == (
        "app.open,desktop.verify"
    )
    assert started["started"] is True
    assert started["running"] is True
    assert started["source"] == "managed_external_provider_session"
    assert started["provider_id"] == "managed-virtual-desktop"
    assert started["desktop_session_kind"] == "virtual_desktop"
    assert started["desktop_backend_kind"] == "virtual_desktop_backend"
    assert started["desktop_backend_ready_for_public_release"] is True
    assert session_module.os.environ["OHA_YACHIYO_DESKTOP_PROVIDER_URL"] == (
        "http://127.0.0.1:29093"
    )
    assert session_module.os.environ["OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL"] == (
        "http://127.0.0.1:29093/tools/execute"
    )

    manager.stop()


def test_start_isolated_provider_session_surfaces_managed_external_start_failure(
    monkeypatch,
    tmp_path,
) -> None:
    for key in session_module._ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST", raising=False)
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND",
        "python -m fake_virtual_desktop_provider",
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_START_CWD", str(tmp_path))
    processes: list[Any] = []

    class FakeProcess:
        pid = 5353

        def __init__(self) -> None:
            payload = {
                "ok": False,
                "error": "provider refused api_key=sk-api-error-secret123456",
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
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(session_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        session_module,
        "desktop_execution_provider_status_from_env",
        lambda *args, **kwargs: {
            "configured": False,
            "available": False,
            "adapter_ready": False,
            "status": "not_configured",
        },
    )
    manager = IsolatedDesktopProviderSessionManager(repo_root=Path("/repo"))
    monkeypatch.setattr(session_module, "_SESSION_MANAGER", manager)

    started = session_module.start_isolated_desktop_provider_session(
        {
            "tools": ["app.open"],
            "requires_real_virtual_desktop_backend": True,
        }
    )

    assert processes[0].terminated is True
    assert started["ok"] is False
    assert started["status"] == "start_failed"
    assert started["running"] is False
    assert started["started"] is False
    assert started["reason"] == "managed_external_provider_start_failed"
    assert started["source"] == "managed_external_provider_session"
    assert started["provider_id"] == "managed-external-desktop"
    assert started["requires_real_virtual_desktop_backend"] is True
    assert "managed_external_provider_start_failed" in started[
        "blocking_conditions"
    ]
    assert "real_virtual_desktop_backend_required" in started[
        "blocking_conditions"
    ]
    assert "sk-api-error-secret123456" not in started["error"]
    assert started["provider_conformance"]["mode"] == (
        "managed_external_provider_start_check"
    )
    assert started["provider_conformance"]["public_release_ready"] is False
    assert "managed_external_provider_start_failed" in started[
        "provider_conformance"
    ]["release_blocking_conditions"]
    assert "OHA_YACHIYO_DESKTOP_PROVIDER_URL" not in session_module.os.environ


def test_start_isolated_provider_session_requires_real_virtual_backend(
    monkeypatch,
) -> None:
    for key in session_module._ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST", raising=False)
    start_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        session_module._SESSION_MANAGER,
        "status",
        lambda probe_health=True: {"ok": True, "status": "stopped", "running": False},
    )
    monkeypatch.setattr(
        session_module._SESSION_MANAGER,
        "start",
        lambda **kwargs: start_calls.append(dict(kwargs)) or {},
    )
    monkeypatch.setattr(
        session_module,
        "desktop_execution_provider_status_from_env",
        lambda *args, **kwargs: {
            "configured": False,
            "available": False,
            "adapter_ready": False,
            "provider_kind": "sandbox_desktop",
            "provider_id": "",
            "status": "not_configured",
        },
    )

    started = session_module.start_isolated_desktop_provider_session(
        {
            "provider_id": "local-isolated-desktop",
            "tools": ["app.open"],
            "requires_real_virtual_desktop_backend": True,
        }
    )

    assert start_calls == []
    assert started["ok"] is False
    assert started["running"] is False
    assert started["started"] is False
    assert started["status"] == "real_virtual_desktop_provider_required"
    assert started["provider_id"] == "local-isolated-desktop"
    assert started["requires_real_virtual_desktop_backend"] is True
    assert "configured_virtual_desktop_provider_required" in started[
        "blocking_conditions"
    ]
    assert "real_virtual_desktop_backend_required" in started["blocking_conditions"]


def test_start_isolated_provider_session_can_start_provider_from_manifest(
    monkeypatch,
    tmp_path,
) -> None:
    for key in session_module._ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND", raising=False)
    manifest_path = tmp_path / "provider-manifest.json"
    provider_script = tmp_path / "provider.py"
    provider_script.write_text("# fake provider\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "provider_id": "manifest-virtual-desktop",
                "provider_kind": "sandbox_desktop",
                "supported_tools": ["app.open", "desktop.verify"],
                "keyboard_mouse_capture_supported": True,
                "foreground_mutation_supported": True,
                "desktop_session_kind": "virtual_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "desktop_backend_kind": "vnc_virtual_desktop",
                "desktop_backend_is_loopback": False,
                "desktop_backend_ready_for_public_release": True,
                "requires_real_virtual_desktop_backend": False,
                "entrypoint": {
                    "script": "provider.py",
                    "args": ["--host", "127.0.0.1", "--port", "0"],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST", str(manifest_path))
    popen_calls: list[dict[str, Any]] = []

    class FakeProcess:
        pid = 6262

        def __init__(self) -> None:
            payload = {
                "ok": True,
                "url": "http://127.0.0.1:29095",
                "execute_url": "http://127.0.0.1:29095/tools/execute",
                "status_url": "http://127.0.0.1:29095/status",
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

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        popen_calls.append({"command": command, **kwargs})
        return FakeProcess()

    def fake_provider_status(env=None, probe_health=False):
        clean_env = dict(env or {})
        configured = bool(clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_URL"))
        return {
            "configured": configured,
            "available": configured,
            "adapter_ready": configured,
            "provider_id": clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_ID", ""),
            "endpoint_origin": clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_URL", ""),
            "status": "available" if configured else "not_configured",
            "probe_health": probe_health,
            "desktop_session_kind": clean_env.get(
                "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
                "",
            ),
            "desktop_session_isolated": True if configured else None,
            "foreground_takeover_required": False if configured else None,
            "keyboard_mouse_capture_supported": True if configured else None,
            "desktop_backend_kind": clean_env.get(
                "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND",
                "",
            ),
            "desktop_backend_is_loopback": (
                clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK")
                == "true"
                if configured
                else None
            ),
            "desktop_backend_ready_for_public_release": (
                clean_env.get(
                    "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE"
                )
                == "true"
                if configured
                else None
            ),
            "requires_real_virtual_desktop_backend": (
                clean_env.get(
                    "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND"
                )
                == "true"
                if configured
                else None
            ),
            "supported_tools": ["app.open", "desktop.verify"] if configured else [],
        }

    monkeypatch.setattr(session_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        session_module,
        "desktop_execution_provider_status_from_env",
        fake_provider_status,
    )

    manager = IsolatedDesktopProviderSessionManager(repo_root=Path("/repo"))
    monkeypatch.setattr(session_module, "_SESSION_MANAGER", manager)

    started = session_module.start_isolated_desktop_provider_session(
        {"tools": ["app.open", "desktop.verify"]}
    )

    assert popen_calls[0]["command"] == [
        sys.executable,
        str(provider_script),
        "--host",
        "127.0.0.1",
        "--port",
        "0",
    ]
    assert popen_calls[0]["cwd"] == str(tmp_path)
    assert popen_calls[0]["env"]["OHA_YACHIYO_DESKTOP_PROVIDER_REQUESTED_TOOLS"] == (
        "app.open,desktop.verify"
    )
    assert started["started"] is True
    assert started["source"] == "managed_external_provider_session"
    assert started["provider_id"] == "manifest-virtual-desktop"
    assert started["desktop_session_kind"] == "virtual_desktop"
    assert started["desktop_backend_kind"] == "vnc_virtual_desktop"
    assert started["desktop_backend_is_loopback"] is False
    assert started["desktop_backend_ready_for_public_release"] is True
    assert started["requires_real_virtual_desktop_backend"] is False
    assert session_module.os.environ["OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL"] == (
        "http://127.0.0.1:29095/tools/execute"
    )
    assert session_module.os.environ["OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND"] == (
        "vnc_virtual_desktop"
    )
    assert session_module.os.environ[
        "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE"
    ] == "true"
    assert session_module.os.environ[
        "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND"
    ] == "false"

    manager.stop()


def test_start_manifest_provider_satisfies_real_virtual_backend_contract(
    monkeypatch,
    tmp_path,
) -> None:
    for key in session_module._ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND", raising=False)
    manifest_path = tmp_path / "release-provider-manifest.json"
    provider_script = tmp_path / "release_provider.py"
    provider_script.write_text("# fake release provider\n", encoding="utf-8")
    release_tools = list(OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS)
    manifest_path.write_text(
        json.dumps(
            {
                "provider_id": "release-virtual-desktop",
                "provider_kind": "sandbox_desktop",
                "supported_tools": release_tools,
                "keyboard_mouse_capture_supported": True,
                "foreground_mutation_supported": True,
                "desktop_session_kind": "virtual_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "desktop_backend_kind": "vnc_virtual_desktop",
                "desktop_backend_is_loopback": False,
                "desktop_backend_ready_for_public_release": True,
                "requires_real_virtual_desktop_backend": False,
                "entrypoint": {"script": "release_provider.py"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST", str(manifest_path))
    popen_calls: list[list[str]] = []

    class FakeProcess:
        pid = 6363

        def __init__(self) -> None:
            payload = {
                "ok": True,
                "url": "http://127.0.0.1:29097",
                "execute_url": "http://127.0.0.1:29097/tools/execute",
                "status_url": "http://127.0.0.1:29097/status",
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

    def fake_provider_status(env=None, probe_health=False):
        clean_env = dict(env or {})
        configured = bool(clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_URL"))
        return {
            "configured": configured,
            "available": configured,
            "adapter_ready": configured,
            "provider_id": clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_ID", ""),
            "status": "available" if configured else "not_configured",
            "probe_health": probe_health,
            "desktop_session_kind": clean_env.get(
                "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
                "",
            ),
            "desktop_session_isolated": True if configured else None,
            "foreground_takeover_required": False if configured else None,
            "keyboard_mouse_capture_supported": True if configured else None,
            "desktop_backend_kind": clean_env.get(
                "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND",
                "",
            ),
            "desktop_backend_is_loopback": False if configured else None,
            "desktop_backend_ready_for_public_release": True if configured else None,
            "requires_real_virtual_desktop_backend": False if configured else None,
            "supported_tools": release_tools if configured else [],
        }

    monkeypatch.setattr(session_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        session_module,
        "desktop_execution_provider_status_from_env",
        fake_provider_status,
    )
    manager = IsolatedDesktopProviderSessionManager(repo_root=Path("/repo"))
    monkeypatch.setattr(session_module, "_SESSION_MANAGER", manager)

    started = session_module.start_isolated_desktop_provider_session(
        {
            "tools": ["app.open"],
            "requires_real_virtual_desktop_backend": True,
        }
    )

    assert popen_calls[0] == [sys.executable, str(provider_script)]
    assert started["started"] is True
    assert started["running"] is True
    assert started["provider_id"] == "release-virtual-desktop"
    assert started["desktop_backend_kind"] == "vnc_virtual_desktop"
    assert started["desktop_backend_is_loopback"] is False
    assert started["requires_real_virtual_desktop_backend"] is False
    assert started["provider_contract"]["ok"] is True
    assert started["provider_contract"]["missing_required_tools"] == []
    assert started["provider_conformance"]["ok"] is True
    assert started["provider_conformance"]["public_release_ready"] is True
    assert started["provider_conformance"]["release_blocking_conditions"] == []
    assert started["provider_conformance"]["covered_tools"] == list(
        OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS
    )

    event_payload = desktop_provider_session_event_payload(started)
    assert event_payload["provider_conformance"]["public_release_ready"] is True

    manager.stop()


def test_isolated_provider_session_status_can_use_manifest_endpoint(
    monkeypatch,
    tmp_path,
) -> None:
    for key in session_module._ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND", raising=False)
    manifest_path = tmp_path / "provider-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "provider_id": "manifest-running-desktop",
                "provider_kind": "sandbox_desktop",
                "endpoint_urls": {
                    "status": "http://127.0.0.1:29096/status",
                    "execute": "http://127.0.0.1:29096/tools/execute",
                },
                "supported_tools": ["app.open", "desktop.verify"],
                "keyboard_mouse_capture_supported": True,
                "desktop_session_kind": "virtual_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "desktop_backend_kind": "vnc_virtual_desktop",
                "desktop_backend_is_loopback": False,
                "desktop_backend_ready_for_public_release": True,
                "requires_real_virtual_desktop_backend": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST", str(manifest_path))

    manager = IsolatedDesktopProviderSessionManager(repo_root=Path("/repo"))
    monkeypatch.setattr(session_module, "_SESSION_MANAGER", manager)
    monkeypatch.setattr(
        manager,
        "status",
        lambda probe_health=True: {"ok": True, "status": "stopped", "running": False},
    )

    def fake_provider_status(env=None, probe_health=False):
        clean_env = dict(env or {})
        configured = bool(clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL"))
        return {
            "configured": configured,
            "available": configured,
            "adapter_ready": configured,
            "provider_id": clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_ID", ""),
            "endpoint_origin": clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_URL", ""),
            "status": "available" if configured else "not_configured",
            "probe_health": probe_health,
            "desktop_session_kind": clean_env.get(
                "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
                "",
            ),
            "desktop_session_isolated": True if configured else None,
            "foreground_takeover_required": False if configured else None,
            "keyboard_mouse_capture_supported": True if configured else None,
            "desktop_backend_kind": clean_env.get(
                "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND",
                "",
            ),
            "desktop_backend_is_loopback": (
                clean_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK")
                == "true"
                if configured
                else None
            ),
            "desktop_backend_ready_for_public_release": (
                clean_env.get(
                    "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE"
                )
                == "true"
                if configured
                else None
            ),
            "requires_real_virtual_desktop_backend": (
                clean_env.get(
                    "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND"
                )
                == "true"
                if configured
                else None
            ),
            "supported_tools": ["app.open", "desktop.verify"] if configured else [],
        }

    monkeypatch.setattr(
        session_module,
        "desktop_execution_provider_status_from_env",
        fake_provider_status,
    )

    try:
        status = session_module.isolated_desktop_provider_session_status()

        assert status["running"] is True
        assert status["source"] == "provider_manifest"
        assert status["provider_id"] == "manifest-running-desktop"
        assert status["desktop_backend_kind"] == "vnc_virtual_desktop"
        assert status["desktop_backend_ready_for_public_release"] is True
        assert status["requires_real_virtual_desktop_backend"] is False
        assert status["env"]["OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL"] == (
            "http://127.0.0.1:29096/tools/execute"
        )
        assert status["env"]["OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND"] == (
            "vnc_virtual_desktop"
        )
        assert session_module.os.environ["OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL"] == (
            "http://127.0.0.1:29096/tools/execute"
        )
    finally:
        for key in session_module._ENV_KEYS:
            session_module.os.environ.pop(key, None)


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


def test_ensure_isolated_provider_session_uses_external_virtual_desktop_provider(
    monkeypatch,
) -> None:
    starts: list[dict[str, Any] | None] = []

    monkeypatch.setattr(
        session_module._SESSION_MANAGER,
        "status",
        lambda probe_health=True: {"ok": True, "status": "stopped", "running": False},
    )
    monkeypatch.setattr(
        session_module,
        "desktop_execution_provider_status_from_env",
        lambda *args, **kwargs: {
            "configured": True,
            "available": True,
            "adapter_ready": True,
            "provider_kind": "sandbox_desktop",
            "provider_id": "real-virtual-desktop",
            "status": "available",
            "endpoint_origin": "http://127.0.0.1:29093",
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "keyboard_mouse_capture_supported": True,
            "desktop_backend_kind": "virtual_desktop_backend",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": True,
            "requires_real_virtual_desktop_backend": False,
            "supported_tools": ["app.open", "desktop.active_window"],
        },
    )
    monkeypatch.setattr(
        session_module,
        "start_isolated_desktop_provider_session",
        lambda request=None: starts.append(request) or {},
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

    assert starts == []
    assert session["needed"] is True
    assert session["running"] is True
    assert session["started"] is False
    assert session["provider_id"] == "real-virtual-desktop"
    assert session["source"] == "runtime_env"
    assert session["desktop_session_kind"] == "virtual_desktop"
    assert session["desktop_session_isolated"] is True
    assert session["foreground_takeover_required"] is False
    assert session["desktop_backend_kind"] == "virtual_desktop_backend"
    assert session["desktop_backend_is_loopback"] is False
    assert session["desktop_backend_ready_for_public_release"] is True
    assert session["requires_real_virtual_desktop_backend"] is False
    assert annotated["requests"][0]["desktop_provider_session"]["provider_id"] == (
        "real-virtual-desktop"
    )


def test_ensure_isolated_provider_session_blocks_external_provider_missing_tools(
    monkeypatch,
) -> None:
    starts: list[dict[str, Any] | None] = []

    monkeypatch.setattr(
        session_module._SESSION_MANAGER,
        "status",
        lambda probe_health=True: {"ok": True, "status": "stopped", "running": False},
    )
    monkeypatch.setattr(
        session_module,
        "desktop_execution_provider_status_from_env",
        lambda *args, **kwargs: {
            "configured": True,
            "available": True,
            "adapter_ready": True,
            "provider_kind": "sandbox_desktop",
            "provider_id": "real-virtual-desktop",
            "status": "available",
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "supported_tools": ["app.open"],
        },
    )
    monkeypatch.setattr(
        session_module,
        "start_isolated_desktop_provider_session",
        lambda request=None: starts.append(request) or {},
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

    assert starts == []
    assert session["needed"] is True
    assert session["ok"] is False
    assert session["running"] is False
    assert session["status"] == "provider_missing_required_tools"
    assert session["reason"] == "isolated_provider_missing_required_tools"
    assert session["provider_id"] == "real-virtual-desktop"


def test_ensure_isolated_provider_session_surfaces_unavailable_external_provider(
    monkeypatch,
) -> None:
    starts: list[dict[str, Any] | None] = []

    monkeypatch.setattr(
        session_module._SESSION_MANAGER,
        "status",
        lambda probe_health=True: {"ok": True, "status": "stopped", "running": False},
    )
    monkeypatch.setattr(
        session_module,
        "desktop_execution_provider_status_from_env",
        lambda *args, **kwargs: {
            "configured": True,
            "available": False,
            "adapter_ready": False,
            "provider_kind": "sandbox_desktop",
            "provider_id": "real-virtual-desktop",
            "status": "provider_unhealthy",
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "blocking_conditions": ["desktop_execution_provider_unhealthy"],
            "supported_tools": ["app.open"],
        },
    )
    monkeypatch.setattr(
        session_module,
        "start_isolated_desktop_provider_session",
        lambda request=None: starts.append(request) or {},
    )
    envelope = {
        "requests": [
            {
                "request_id": "request-open",
                "tool_name": "app.open",
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

    assert starts == []
    assert session["needed"] is True
    assert session["ok"] is False
    assert session["running"] is False
    assert session["status"] == "provider_unhealthy"
    assert session["reason"] == "external_isolated_provider_unavailable"
    assert session["provider_id"] == "real-virtual-desktop"


def test_ensure_isolated_provider_session_starts_managed_external_provider_when_unavailable(
    monkeypatch,
) -> None:
    starts: list[dict[str, Any] | None] = []

    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND",
        "python -m fake_virtual_desktop_provider",
    )
    monkeypatch.setattr(
        session_module._SESSION_MANAGER,
        "status",
        lambda probe_health=True: {"ok": True, "status": "stopped", "running": False},
    )
    monkeypatch.setattr(
        session_module,
        "desktop_execution_provider_status_from_env",
        lambda *args, **kwargs: {
            "configured": True,
            "available": False,
            "adapter_ready": False,
            "provider_kind": "sandbox_desktop",
            "provider_id": "real-virtual-desktop",
            "status": "provider_unhealthy",
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "supported_tools": ["app.open"],
        },
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
            "source": "managed_external_provider_session",
            "provider_id": "real-virtual-desktop",
            "provider_status": {
                "desktop_session_kind": "virtual_desktop",
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

    assert starts == [{"tools": ["app.open"]}]
    assert session["needed"] is True
    assert session["running"] is True
    assert session["started"] is True
    assert session["source"] == "managed_external_provider_session"
    assert session["provider_id"] == "real-virtual-desktop"


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
