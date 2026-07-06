"""Local process session manager for the isolated desktop provider."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from apps.shell.agent.runtime.desktop_execution_providers import (
    desktop_execution_provider_status_from_env,
)
from apps.shell.agent.runtime.isolated_desktop_provider import (
    DEFAULT_ISOLATED_PROVIDER_ID,
)

_ENV_KEYS = {
    "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
    "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
    "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
    "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
    "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
    "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED",
    "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
}


class IsolatedDesktopProviderSessionManager:
    """Starts, stops, and probes a local isolated desktop provider process."""

    def __init__(self, *, repo_root: Path | None = None) -> None:
        self._repo_root = repo_root or Path(__file__).resolve().parents[3]
        self._process: subprocess.Popen[str] | None = None
        self._env: dict[str, str] = {}
        self._command: list[str] = []
        self._started_at = 0.0
        self._lock = threading.RLock()

    def status(self, *, probe_health: bool = True) -> dict[str, Any]:
        with self._lock:
            process = self._process
            running = process is not None and process.poll() is None
            if process is not None and not running:
                _clear_runtime_env(self._env)
                self._process = None
                process = None
                self._env = {}
                self._command = []
                self._started_at = 0.0
            provider_status = (
                desktop_execution_provider_status_from_env(
                    self._env,
                    probe_health=probe_health,
                )
                if self._env
                else {}
            )
            return {
                "ok": True,
                "status": "running" if running else "stopped",
                "running": running,
                "pid": int(process.pid) if running and process is not None else None,
                "provider_id": self._env.get("OHA_YACHIYO_DESKTOP_PROVIDER_ID", ""),
                "url": self._env.get("OHA_YACHIYO_DESKTOP_PROVIDER_URL", ""),
                "command": list(self._command),
                "env": dict(self._env),
                "started_at": self._started_at,
                "provider_status": provider_status,
                "source": "isolated_provider_session_manager",
            }

    def start(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        provider_id: str = DEFAULT_ISOLATED_PROVIDER_ID,
        tools: list[str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> dict[str, Any]:
        with self._lock:
            current = self.status(probe_health=True)
            if current["running"]:
                return {**current, "started": False}
            command = [
                sys.executable,
                str(self._repo_root / "scripts" / "run_isolated_desktop_provider.py"),
                "--host",
                str(host or "127.0.0.1"),
                "--port",
                str(int(port or 0)),
                "--provider-id",
                str(provider_id or DEFAULT_ISOLATED_PROVIDER_ID),
                "--quiet",
            ]
            for tool in tools or []:
                clean_tool = str(tool or "").strip()
                if clean_tool:
                    command.extend(["--tool", clean_tool])
            process = subprocess.Popen(
                command,
                cwd=str(self._repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                launch = _read_launch_payload(process, timeout_seconds=timeout_seconds)
            except Exception:
                _terminate_process(process)
                raise
            env = _runtime_env_from_launch(launch)
            self._process = process
            self._command = command
            self._env = env
            self._started_at = time.time()
            _apply_runtime_env(env)
            return {**self.status(probe_health=True), "started": True, "launch": launch}

    def stop(self, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
        with self._lock:
            process = self._process
            was_running = process is not None and process.poll() is None
            if was_running and process is not None:
                _terminate_process(process, timeout_seconds=timeout_seconds)
            _clear_runtime_env(self._env)
            self._process = None
            self._env = {}
            self._command = []
            self._started_at = 0.0
            return {
                "ok": True,
                "status": "stopped",
                "running": False,
                "stopped": was_running,
                "source": "isolated_provider_session_manager",
            }


def isolated_desktop_provider_session_manager() -> IsolatedDesktopProviderSessionManager:
    return _SESSION_MANAGER


def isolated_desktop_provider_session_status() -> dict[str, Any]:
    return _SESSION_MANAGER.status(probe_health=True)


def start_isolated_desktop_provider_session(
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(request or {})
    tools = payload.get("tools")
    return _SESSION_MANAGER.start(
        host=str(payload.get("host") or "127.0.0.1"),
        port=int(payload.get("port") or 0),
        provider_id=str(
            payload.get("provider_id") or DEFAULT_ISOLATED_PROVIDER_ID
        ),
        tools=[str(item) for item in tools] if isinstance(tools, list) else None,
    )


def stop_isolated_desktop_provider_session() -> dict[str, Any]:
    return _SESSION_MANAGER.stop()


def _read_launch_payload(
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    output: queue.Queue[str] = queue.Queue(maxsize=1)

    def read_line() -> None:
        if process.stdout is None:
            return
        output.put(process.stdout.readline())

    thread = threading.Thread(target=read_line, daemon=True)
    thread.start()
    try:
        line = output.get(timeout=max(0.1, timeout_seconds))
    except queue.Empty as exc:
        raise RuntimeError("isolated desktop provider did not report launch status") from exc
    if process.poll() is not None and not line:
        stderr = process.stderr.read() if process.stderr is not None else ""
        raise RuntimeError(f"isolated desktop provider exited early: {stderr}")
    payload = json.loads(str(line or "{}"))
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError("isolated desktop provider launch failed")
    return payload


def _runtime_env_from_launch(launch: dict[str, Any]) -> dict[str, str]:
    supported_tools = launch.get("supported_tools")
    tools = (
        ",".join(str(item) for item in supported_tools)
        if isinstance(supported_tools, list)
        else "desktop.safe_type_text"
    )
    return {
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL": str(launch.get("url") or ""),
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID": str(launch.get("provider_id") or ""),
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": tools,
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED": "true",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND": "isolated_desktop",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED": "true",
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED": "false",
    }


def _apply_runtime_env(env: dict[str, str]) -> None:
    for key, value in env.items():
        if key in _ENV_KEYS:
            os.environ[key] = value


def _clear_runtime_env(env: dict[str, str]) -> None:
    for key in _ENV_KEYS:
        if os.environ.get(key) == env.get(key):
            os.environ.pop(key, None)


def _terminate_process(
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float = 5.0,
) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=max(0.1, timeout_seconds))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


_SESSION_MANAGER = IsolatedDesktopProviderSessionManager()
