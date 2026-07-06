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

from apps.shell.agent.runtime.controlled_desktop_provider import (
    KEYBOARD_MOUSE_CONTROL_TOOLS,
)
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

_PROVIDER_START_STATUSES = {
    "provider_required",
    "sandbox_keyboard_mouse_provider_required",
    "sandbox_desktop_session_required",
    "sandbox_adapter_required",
}

_PROVIDER_START_BLOCKERS = {
    "sandbox_desktop_provider_required",
    "sandbox_keyboard_mouse_provider_required",
    "sandbox_desktop_session_required",
    "sandbox_desktop_adapter_required",
    "isolated_desktop_provider_required",
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


def ensure_isolated_desktop_provider_session_for_envelope(
    envelope: dict[str, Any] | None,
    *,
    auto_start: bool = True,
) -> dict[str, Any]:
    """Start the local isolated provider when a runtime envelope needs it."""

    targets = _isolated_session_targets(envelope)
    status = isolated_desktop_provider_session_status()
    base = {
        "ok": True,
        "needed": bool(targets),
        "auto_start": bool(auto_start),
        "started": False,
        "request_ids": [target["request_id"] for target in targets],
        "tool_names": sorted({target["tool_name"] for target in targets}),
        "reason": "isolated_provider_required" if targets else "",
        "source": "isolated_provider_session_manager",
    }
    if not targets:
        return {**base, **_public_session_status(status)}
    if bool(status.get("running")):
        return {**base, **_public_session_status(status), "running": True}
    if not auto_start:
        return {**base, **_public_session_status(status)}
    try:
        started = start_isolated_desktop_provider_session()
    except Exception as exc:
        return {
            **base,
            "ok": False,
            "status": "start_failed",
            "running": False,
            "error": str(exc),
        }
    return {
        **base,
        **_public_session_status(started),
        "started": bool(started.get("started")),
    }


def annotate_envelope_with_desktop_provider_session(
    envelope: dict[str, Any],
    session: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(envelope)
    if not session:
        return payload
    public_session = _public_session_status(session)
    public_session.update(
        {
            key: session[key]
            for key in (
                "needed",
                "auto_start",
                "started",
                "reason",
                "request_ids",
                "tool_names",
            )
            if key in session
        }
    )
    payload["desktop_provider_session"] = public_session
    request_ids = set(_string_list(session.get("request_ids")))
    requests = payload.get("requests")
    if isinstance(requests, list):
        payload["requests"] = [
            _request_with_desktop_provider_session(request, public_session, request_ids)
            if isinstance(request, dict)
            else request
            for request in requests
        ]
    return payload


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


def _isolated_session_targets(envelope: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(envelope, dict):
        return []
    targets: list[dict[str, str]] = []
    requests = envelope.get("requests")
    if not isinstance(requests, list):
        return targets
    for index, request in enumerate(requests, start=1):
        if not isinstance(request, dict):
            continue
        tool_name = _request_tool_name(request)
        if not _request_needs_isolated_session(tool_name, request):
            continue
        request_id = str(
            request.get("request_id") or f"request:{index}:{tool_name}"
        ).strip()
        targets.append({"request_id": request_id, "tool_name": tool_name})
    return targets


def _request_needs_isolated_session(tool_name: str, request: dict[str, Any]) -> bool:
    if tool_name not in KEYBOARD_MOUSE_CONTROL_TOOLS:
        return False
    route = _mapping(request.get("desktop_execution_route"))
    provider = _mapping(request.get("sandbox_provider"))
    mode = _mapping(request.get("execution_mode"))
    route_status = str(route.get("status") or "").strip()
    route_blockers = set(_string_list(route.get("blocking_conditions")))
    provider_blockers = set(_string_list(provider.get("blocking_conditions")))
    if route_status in _PROVIDER_START_STATUSES:
        return True
    if route_blockers & _PROVIDER_START_BLOCKERS:
        return True
    if provider_blockers & _PROVIDER_START_BLOCKERS:
        return True
    if (
        bool(mode.get("keyboard_mouse_capture"))
        and provider.get("desktop_session_isolated") is not True
    ):
        return True
    return False


def _request_with_desktop_provider_session(
    request: dict[str, Any],
    session: dict[str, Any],
    request_ids: set[str],
) -> dict[str, Any]:
    if request_ids and str(request.get("request_id") or "").strip() not in request_ids:
        return request
    if not request_ids and not _request_needs_isolated_session(
        _request_tool_name(request),
        request,
    ):
        return request
    return {**request, "desktop_provider_session": dict(session)}


def _public_session_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(status.get("ok", True)),
        "status": str(status.get("status") or ""),
        "running": bool(status.get("running")),
        "pid": status.get("pid"),
        "provider_id": str(status.get("provider_id") or ""),
        "url": str(status.get("url") or ""),
        "command": _string_list(status.get("command")),
        "env": {
            str(key): str(value)
            for key, value in (status.get("env") or {}).items()
            if str(key).strip()
        }
        if isinstance(status.get("env"), dict)
        else {},
        "source": str(status.get("source") or "isolated_provider_session_manager"),
    }


def _request_tool_name(request: dict[str, Any]) -> str:
    return str(request.get("tool_name") or request.get("tool") or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, list):
        raw = value
    else:
        raw = []
    return [str(item or "").strip() for item in raw if str(item or "").strip()]


_SESSION_MANAGER = IsolatedDesktopProviderSessionManager()
