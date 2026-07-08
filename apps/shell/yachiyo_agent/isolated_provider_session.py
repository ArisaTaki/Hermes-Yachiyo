"""Local process session manager for the isolated desktop provider."""

from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from apps.shell.agent.runtime.controlled_desktop_provider import (
    CONTROLLED_DESKTOP_PROVIDER_TOOLS,
    KEYBOARD_MOUSE_CONTROL_TOOLS,
)
from apps.shell.agent.runtime.desktop_execution_providers import (
    desktop_execution_provider_status_from_env,
)
from apps.shell.agent.runtime.isolated_desktop_provider import (
    DEFAULT_ISOLATED_PROVIDER_ID,
)
from apps.shell.yachiyo_agent.desktop_execution_policy import (
    is_user_foreground_takeover_tool,
    user_foreground_takeover_allowed,
)

_ENV_KEYS = {
    "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
    "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL",
    "OHA_YACHIYO_DESKTOP_PROVIDER_STATUS_URL",
    "OHA_YACHIYO_DESKTOP_PROVIDER_KIND",
    "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
    "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
    "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
    "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_MUTATION_SUPPORTED",
    "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
    "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED",
    "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
    "OHA_YACHIYO_DESKTOP_PROVIDER_ALLOW_REMOTE",
}

_PROVIDER_START_COMMAND_ENV = "OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND"
_PROVIDER_START_CWD_ENV = "OHA_YACHIYO_DESKTOP_PROVIDER_START_CWD"
_PROVIDER_MANIFEST_ENV = "OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST"
_PROVIDER_REQUESTED_TOOLS_ENV = "OHA_YACHIYO_DESKTOP_PROVIDER_REQUESTED_TOOLS"

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
        self._source = "isolated_provider_session_manager"
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
                self._source = "isolated_provider_session_manager"
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
                "desktop_session_kind": str(
                    provider_status.get("desktop_session_kind") or ""
                ),
                "desktop_session_isolated": _optional_bool(
                    provider_status.get("desktop_session_isolated")
                ),
                "foreground_takeover_required": _optional_bool(
                    provider_status.get("foreground_takeover_required")
                ),
                "keyboard_mouse_capture_supported": _optional_bool(
                    provider_status.get("keyboard_mouse_capture_supported")
                ),
                "desktop_backend_kind": str(
                    provider_status.get("desktop_backend_kind") or ""
                ),
                "desktop_backend_is_loopback": _optional_bool(
                    provider_status.get("desktop_backend_is_loopback")
                ),
                "desktop_backend_ready_for_public_release": _optional_bool(
                    provider_status.get("desktop_backend_ready_for_public_release")
                ),
                "requires_real_virtual_desktop_backend": _optional_bool(
                    provider_status.get("requires_real_virtual_desktop_backend")
                ),
                "supported_tools": _string_list(provider_status.get("supported_tools")),
                "source": self._source,
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
            self._source = "isolated_provider_session_manager"
            self._started_at = time.time()
            _apply_runtime_env(env)
            return {**self.status(probe_health=True), "started": True, "launch": launch}

    def start_managed_external(
        self,
        *,
        tools: list[str] | None = None,
        timeout_seconds: float = 10.0,
    ) -> dict[str, Any]:
        with self._lock:
            current = self.status(probe_health=True)
            if current["running"]:
                return {**current, "started": False}
            manifest = _managed_external_provider_manifest(self._repo_root)
            command = _managed_external_provider_start_command(
                self._repo_root,
                manifest=manifest,
            )
            if not command:
                raise RuntimeError("desktop provider start command is not configured")
            start_env = dict(os.environ)
            requested_tools = sorted(
                {
                    str(item or "").strip()
                    for item in tools or []
                    if str(item or "").strip()
                }
            )
            if requested_tools:
                start_env[_PROVIDER_REQUESTED_TOOLS_ENV] = ",".join(requested_tools)
            process = subprocess.Popen(
                command,
                cwd=str(
                    _managed_external_provider_start_cwd(
                        self._repo_root,
                        manifest=manifest,
                    )
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=start_env,
            )
            try:
                launch = _read_launch_payload(
                    process,
                    timeout_seconds=timeout_seconds,
                    label="managed desktop provider",
                )
            except Exception:
                _terminate_process(process)
                raise
            env = _runtime_env_from_launch(_merge_manifest_launch(manifest, launch))
            self._process = process
            self._command = command
            self._env = env
            self._source = "managed_external_provider_session"
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
            self._source = "isolated_provider_session_manager"
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
    local_status = _SESSION_MANAGER.status(probe_health=True)
    if bool(local_status.get("running")):
        return local_status
    external_status = _external_isolated_desktop_provider_session_status()
    if external_status:
        return external_status
    return local_status


def start_isolated_desktop_provider_session(
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(request or {})
    tools = payload.get("tools")
    clean_tools = [str(item) for item in tools] if isinstance(tools, list) else None
    external_status = _external_isolated_desktop_provider_session_status()
    if bool(external_status.get("running")) and _session_status_supports_targets(
        external_status,
        [{"request_id": "", "tool_name": tool} for tool in clean_tools or []],
    ):
        return {**external_status, "started": False}
    if _managed_external_provider_start_configured():
        return _SESSION_MANAGER.start_managed_external(tools=clean_tools)
    return _SESSION_MANAGER.start(
        host=str(payload.get("host") or "127.0.0.1"),
        port=int(payload.get("port") or 0),
        provider_id=str(
            payload.get("provider_id") or DEFAULT_ISOLATED_PROVIDER_ID
        ),
        tools=clean_tools,
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
    scoped_targets = _isolated_session_scope_targets(envelope, targets)
    status = isolated_desktop_provider_session_status()
    base = {
        "ok": True,
        "needed": bool(targets),
        "auto_start": bool(auto_start),
        "started": False,
        "request_ids": [target["request_id"] for target in scoped_targets],
        "tool_names": sorted({target["tool_name"] for target in scoped_targets}),
        "reason": "isolated_provider_required" if targets else "",
        "source": "isolated_provider_session_manager",
    }
    if not targets:
        return {**base, **_public_session_status(status)}
    if bool(status.get("running")) and _session_status_supports_targets(
        status,
        scoped_targets,
    ):
        return {**base, **_public_session_status(status), "running": True}
    if bool(status.get("running")):
        return {
            **base,
            **_public_session_status(status),
            "ok": False,
            "running": False,
            "status": "provider_missing_required_tools",
            "reason": "isolated_provider_missing_required_tools",
        }
    if (
        status.get("external_provider_configured") is True
        and not _managed_external_provider_start_configured()
    ):
        return {
            **base,
            **_public_session_status(status),
            "ok": False,
            "running": False,
            "reason": "external_isolated_provider_unavailable",
        }
    if not auto_start:
        return {**base, **_public_session_status(status)}
    try:
        started = start_isolated_desktop_provider_session(
            {"tools": sorted({target["tool_name"] for target in scoped_targets})}
        )
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
                "error",
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
    label: str = "isolated desktop provider",
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
        raise RuntimeError(f"{label} did not report launch status") from exc
    if process.poll() is not None and not line:
        stderr = process.stderr.read() if process.stderr is not None else ""
        raise RuntimeError(f"{label} exited early: {stderr}")
    payload = json.loads(str(line or "{}"))
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError(f"{label} launch failed")
    return payload


def _runtime_env_from_launch(launch: dict[str, Any]) -> dict[str, str]:
    launch = _provider_runtime_payload(launch)
    supported_tools = _string_list(launch.get("supported_tools"))
    tools = ",".join(supported_tools) if supported_tools else "desktop.safe_type_text"
    env = {
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL": str(
            launch.get("url") or launch.get("endpoint_origin") or ""
        ),
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID": str(launch.get("provider_id") or ""),
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": tools,
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED": _bool_env_value(
            launch.get("keyboard_mouse_capture_supported"),
            default=True,
        ),
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND": str(
            launch.get("desktop_session_kind")
            or launch.get("session_kind")
            or "isolated_desktop"
        ),
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED": _bool_env_value(
            launch.get("desktop_session_isolated"),
            default=True,
        ),
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED": _bool_env_value(
            launch.get("foreground_takeover_required"),
            default=False,
        ),
    }
    optional_keys = {
        "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL": "execute_url",
        "OHA_YACHIYO_DESKTOP_PROVIDER_STATUS_URL": "status_url",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KIND": "provider_kind",
        "OHA_YACHIYO_DESKTOP_PROVIDER_ALLOW_REMOTE": "allow_remote",
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_MUTATION_SUPPORTED": (
            "foreground_mutation_supported"
        ),
    }
    for env_key, launch_key in optional_keys.items():
        value = launch.get(launch_key)
        if value not in (None, "", [], {}):
            if isinstance(value, bool):
                env[env_key] = "true" if value else "false"
            else:
                env[env_key] = str(value)
    return env


def _managed_external_provider_start_configured() -> bool:
    if str(os.environ.get(_PROVIDER_START_COMMAND_ENV) or "").strip():
        return True
    return bool(str(os.environ.get(_PROVIDER_MANIFEST_ENV) or "").strip())


def _managed_external_provider_start_command(
    repo_root: Path,
    *,
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    raw = str(os.environ.get(_PROVIDER_START_COMMAND_ENV) or "").strip()
    if raw:
        return shlex.split(raw)
    manifest_payload = (
        manifest
        if manifest is not None
        else _managed_external_provider_manifest(repo_root)
    )
    entrypoint = _mapping(manifest_payload.get("entrypoint"))
    command = entrypoint.get("command") or entrypoint.get("argv")
    if isinstance(command, str):
        return shlex.split(command)
    if isinstance(command, list):
        return [str(item) for item in command if str(item or "").strip()]
    args = _string_list(entrypoint.get("args"))
    script = str(entrypoint.get("script") or "").strip()
    if script:
        cwd = _managed_external_provider_start_cwd(
            repo_root,
            manifest=manifest_payload,
        )
        return [
            sys.executable,
            str(
                _resolve_manifest_entrypoint_path(
                    script,
                    cwd=cwd,
                    repo_root=repo_root,
                )
            ),
            *args,
        ]
    module = str(entrypoint.get("module") or "").strip()
    if module:
        return [sys.executable, "-m", module, *args]
    return []


def _managed_external_provider_start_cwd(
    repo_root: Path,
    *,
    manifest: dict[str, Any] | None = None,
) -> Path:
    raw = str(os.environ.get(_PROVIDER_START_CWD_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser()
    entrypoint = _mapping((manifest or {}).get("entrypoint"))
    cwd = str(entrypoint.get("cwd") or "").strip()
    if cwd:
        path = Path(cwd).expanduser()
        return path if path.is_absolute() else repo_root / path
    manifest_path = _managed_external_provider_manifest_path(repo_root)
    return manifest_path.parent if manifest_path is not None else repo_root


def _managed_external_provider_manifest(repo_root: Path | None = None) -> dict[str, Any]:
    path = _managed_external_provider_manifest_path(repo_root)
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("desktop provider manifest must be a JSON object")
    return payload


def _managed_external_provider_manifest_path(
    repo_root: Path | None = None,
) -> Path | None:
    raw = str(os.environ.get(_PROVIDER_MANIFEST_ENV) or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    base = repo_root or Path.cwd()
    return base / path


def _merge_manifest_launch(
    manifest: dict[str, Any],
    launch: dict[str, Any],
) -> dict[str, Any]:
    payload = _provider_runtime_payload(manifest)
    launch_payload = _provider_runtime_payload(launch)
    payload.update(launch_payload)
    if launch_payload.get("url") and "execute_url" not in launch_payload:
        payload.pop("execute_url", None)
    if launch_payload.get("url") and "status_url" not in launch_payload:
        payload.pop("status_url", None)
    return payload


def _provider_runtime_payload(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    payload = dict(config)
    safety = _mapping(payload.get("safety"))
    for key in (
        "foreground_mutation_supported",
        "keyboard_mouse_capture_supported",
        "desktop_session_kind",
        "desktop_session_isolated",
        "foreground_takeover_required",
        "desktop_backend_kind",
        "desktop_backend_is_loopback",
        "desktop_backend_ready_for_public_release",
        "requires_real_virtual_desktop_backend",
    ):
        if payload.get(key) in (None, "", [], {}) and key in safety:
            payload[key] = safety.get(key)
    endpoint_urls = _mapping(payload.get("endpoint_urls"))
    if not endpoint_urls:
        endpoint_urls = {
            key: value
            for key, value in _mapping(payload.get("endpoints")).items()
            if str(value or "").startswith(("http://", "https://"))
        }
    execute_url = _first_mapping_value(
        endpoint_urls,
        "execute",
        "tools_execute",
        "tools.execute",
        "tools/execute",
        "execute_url",
    )
    status_url = _first_mapping_value(endpoint_urls, "status", "health", "status_url")
    base_url = (
        _first_mapping_value(payload, "url", "endpoint_origin", "base_url")
        or _first_mapping_value(endpoint_urls, "url", "base_url", "base", "origin")
        or _url_origin(str(execute_url or status_url or ""))
    )
    if base_url:
        payload["url"] = str(base_url)
    if execute_url:
        payload["execute_url"] = str(execute_url)
    if status_url:
        payload["status_url"] = str(status_url)
    return payload


def _resolve_manifest_entrypoint_path(
    value: str,
    *,
    cwd: Path,
    repo_root: Path,
) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    cwd_path = cwd / path
    if cwd_path.exists():
        return cwd_path
    repo_path = repo_root / path
    if repo_path.exists():
        return repo_path
    return cwd_path


def _first_mapping_value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _url_origin(value: str) -> str:
    parsed = urlparse(str(value or ""))
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _bool_env_value(value: Any, *, default: bool) -> str:
    parsed = _optional_bool(value)
    if parsed is None:
        parsed = default
    return "true" if parsed else "false"


def _external_isolated_desktop_provider_session_status() -> dict[str, Any]:
    provider_status = desktop_execution_provider_status_from_env(probe_health=True)
    env_snapshot = _provider_env_snapshot()
    source = "runtime_env"
    is_candidate = _external_status_is_isolated_provider_candidate(provider_status)
    running = bool(provider_status.get("available")) and bool(
        provider_status.get("adapter_ready")
    )
    if (
        not is_candidate
        or (
            not running
            and str(os.environ.get(_PROVIDER_MANIFEST_ENV) or "").strip()
        )
    ):
        try:
            manifest_env = _runtime_env_from_launch(
                _managed_external_provider_manifest(_SESSION_MANAGER._repo_root)
            )
        except Exception:
            manifest_env = {}
        if manifest_env:
            provider_status = desktop_execution_provider_status_from_env(
                manifest_env,
                probe_health=True,
            )
            if _external_status_is_isolated_provider_candidate(provider_status):
                _apply_runtime_env(manifest_env)
                env_snapshot = dict(manifest_env)
                source = "provider_manifest"
            else:
                if not is_candidate:
                    return {}
        else:
            if not is_candidate:
                return {}
    running = bool(provider_status.get("available")) and bool(
        provider_status.get("adapter_ready")
    )
    return {
        "ok": bool(provider_status.get("available", True)),
        "status": str(
            provider_status.get("status")
            or ("running" if running else "external_provider_unavailable")
        ),
        "running": running,
        "pid": None,
        "provider_id": str(provider_status.get("provider_id") or ""),
        "url": str(
            env_snapshot.get("OHA_YACHIYO_DESKTOP_PROVIDER_URL")
            or os.environ.get("OHA_YACHIYO_DESKTOP_PROVIDER_URL")
            or provider_status.get("endpoint_origin")
            or ""
        ),
        "command": [],
        "env": env_snapshot,
        "started_at": 0.0,
        "provider_status": dict(provider_status),
        "source": source,
        "external_provider_configured": True,
    }


def _external_status_is_isolated_provider_candidate(
    provider_status: dict[str, Any],
) -> bool:
    if not isinstance(provider_status, dict):
        return False
    if provider_status.get("configured") is not True:
        return False
    session_kind = str(provider_status.get("desktop_session_kind") or "").strip()
    session_isolated = _optional_bool(provider_status.get("desktop_session_isolated"))
    foreground_takeover = _optional_bool(
        provider_status.get("foreground_takeover_required")
    )
    return (
        session_isolated is True
        or session_kind in {"isolated_desktop", "virtual_desktop"}
    ) and foreground_takeover is not True


def _provider_env_snapshot() -> dict[str, str]:
    return {
        key: str(os.environ.get(key) or "")
        for key in _ENV_KEYS
        if str(os.environ.get(key) or "").strip()
    }


def _session_status_supports_targets(
    status: dict[str, Any],
    targets: list[dict[str, str]],
) -> bool:
    tool_names = {
        str(target.get("tool_name") or "").strip()
        for target in targets
        if str(target.get("tool_name") or "").strip()
    }
    if not tool_names:
        return True
    supported_tools = set(_string_list(status.get("supported_tools")))
    if not supported_tools:
        provider_status = _mapping(status.get("provider_status"))
        supported_tools = set(_string_list(provider_status.get("supported_tools")))
    return not supported_tools or tool_names.issubset(supported_tools)


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


def _isolated_session_scope_targets(
    envelope: dict[str, Any] | None,
    targets: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not targets or not isinstance(envelope, dict):
        return targets
    requests = envelope.get("requests")
    if not isinstance(requests, list):
        return targets
    scoped: list[dict[str, str]] = []
    seen_request_ids: set[str] = set()
    for index, request in enumerate(requests, start=1):
        if not isinstance(request, dict):
            continue
        tool_name = _request_tool_name(request)
        if tool_name not in CONTROLLED_DESKTOP_PROVIDER_TOOLS:
            continue
        request_id = str(
            request.get("request_id") or f"request:{index}:{tool_name}"
        ).strip()
        if not request_id or request_id in seen_request_ids:
            continue
        scoped.append({"request_id": request_id, "tool_name": tool_name})
        seen_request_ids.add(request_id)
    return scoped or targets


def _request_needs_isolated_session(tool_name: str, request: dict[str, Any]) -> bool:
    route = _mapping(request.get("desktop_execution_route"))
    provider = _mapping(request.get("sandbox_provider"))
    mode = _mapping(request.get("execution_mode"))
    if _request_allows_user_foreground_session(request):
        return False
    if _route_or_provider_already_supplies_isolated_session(route, provider):
        return False
    if _route_or_provider_requires_isolated_session(route, provider):
        return True
    if _request_prefers_isolated_foreground_session(
        tool_name,
        request,
        route=route,
        provider=provider,
        mode=mode,
    ):
        return True
    if tool_name not in KEYBOARD_MOUSE_CONTROL_TOOLS and not bool(
        mode.get("keyboard_mouse_capture")
    ):
        return False
    if _optional_bool(provider.get("desktop_session_isolated")) is True:
        return False
    if _optional_bool(route.get("desktop_session_isolated")) is True:
        return False
    return True


def _request_allows_user_foreground_session(request: dict[str, Any]) -> bool:
    if user_foreground_takeover_allowed(request):
        return True
    policy = _mapping(request.get("desktop_execution_policy"))
    if (
        _optional_bool(policy.get("allow_live_foreground")) is True
        and not _policy_prefers_isolated_foreground(policy)
    ):
        return True
    mode = str(policy.get("mode") or "").strip().lower().replace("-", "_")
    if mode == "allow" and not _policy_prefers_isolated_foreground(policy):
        return True
    return False


def _request_prefers_isolated_foreground_session(
    tool_name: str,
    request: dict[str, Any],
    *,
    route: dict[str, Any],
    provider: dict[str, Any],
    mode: dict[str, Any],
) -> bool:
    if user_foreground_takeover_allowed(request):
        return False
    if _optional_bool(provider.get("desktop_session_isolated")) is True:
        return False
    if _optional_bool(route.get("desktop_session_isolated")) is True:
        return False
    if not (
        is_user_foreground_takeover_tool(tool_name)
        or bool(mode.get("foreground_control"))
        or bool(route.get("user_foreground_takeover_risk"))
    ):
        return False
    if _optional_bool(route.get("requires_user_foreground_session")) is True:
        return True
    if _optional_bool(route.get("user_foreground_takeover_risk")) is True:
        return True
    policy = _mapping(request.get("desktop_execution_policy"))
    if _policy_prefers_isolated_foreground(policy):
        return True
    return False


def _policy_prefers_isolated_foreground(policy: dict[str, Any]) -> bool:
    return any(
        _optional_bool(policy.get(key)) is True
        for key in (
            "prefer_isolated_desktop",
            "avoid_user_foreground_takeover",
            "require_sandbox_for_keyboard_mouse",
        )
    )


def _route_or_provider_already_supplies_isolated_session(
    route: dict[str, Any],
    provider: dict[str, Any],
) -> bool:
    provider_kind = str(
        route.get("selected_provider_kind")
        or route.get("provider_kind")
        or provider.get("provider_kind")
        or ""
    ).strip()
    if provider_kind != "sandbox_desktop":
        return False
    route_status = str(route.get("status") or "").strip()
    provider_status = str(provider.get("status") or "").strip()
    if route_status not in {"sandbox_ready", "provider_ready"} and provider_status not in {
        "available",
        "ready",
        "running",
    }:
        return False
    if _optional_bool(route.get("foreground_takeover_required")) is True:
        return False
    if _optional_bool(provider.get("foreground_takeover_required")) is True:
        return False
    return True


def _route_or_provider_requires_isolated_session(
    route: dict[str, Any],
    provider: dict[str, Any],
) -> bool:
    route_status = str(route.get("status") or "").strip()
    route_blockers = set(_string_list(route.get("blocking_conditions")))
    provider_blockers = set(_string_list(provider.get("blocking_conditions")))
    provider_kind = str(
        route.get("selected_provider_kind")
        or route.get("provider_kind")
        or provider.get("provider_kind")
        or ""
    ).strip()
    provider_requested = (
        provider_kind == "sandbox_desktop"
        or bool(route.get("sandbox_required"))
        or bool(route.get("provider_execution_required"))
        or bool(provider)
    )
    if provider_requested and route_status in _PROVIDER_START_STATUSES:
        return True
    if provider_requested and route_blockers & _PROVIDER_START_BLOCKERS:
        return True
    if provider_requested and provider_blockers & _PROVIDER_START_BLOCKERS:
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
    provider_status = _mapping(status.get("provider_status"))
    return {
        "ok": bool(status.get("ok", True)),
        "status": str(status.get("status") or ""),
        "running": bool(status.get("running")),
        "pid": status.get("pid"),
        "provider_id": str(status.get("provider_id") or ""),
        "url": str(status.get("url") or ""),
        "desktop_session_kind": str(
            status.get("desktop_session_kind")
            or provider_status.get("desktop_session_kind")
            or ""
        ),
        "desktop_session_isolated": _optional_bool(
            status.get("desktop_session_isolated"),
            provider_status.get("desktop_session_isolated"),
        ),
        "foreground_takeover_required": _optional_bool(
            status.get("foreground_takeover_required"),
            provider_status.get("foreground_takeover_required"),
        ),
        "keyboard_mouse_capture_supported": _optional_bool(
            status.get("keyboard_mouse_capture_supported"),
            provider_status.get("keyboard_mouse_capture_supported"),
        ),
        "desktop_backend_kind": str(
            status.get("desktop_backend_kind")
            or provider_status.get("desktop_backend_kind")
            or ""
        ),
        "desktop_backend_is_loopback": _optional_bool(
            status.get("desktop_backend_is_loopback"),
            provider_status.get("desktop_backend_is_loopback"),
        ),
        "desktop_backend_ready_for_public_release": _optional_bool(
            status.get("desktop_backend_ready_for_public_release"),
            provider_status.get("desktop_backend_ready_for_public_release"),
        ),
        "requires_real_virtual_desktop_backend": _optional_bool(
            status.get("requires_real_virtual_desktop_backend"),
            provider_status.get("requires_real_virtual_desktop_backend"),
        ),
        "supported_tools": _string_list(
            status.get("supported_tools") or provider_status.get("supported_tools")
        ),
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


def _optional_bool(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            raw = value.strip().lower()
            if raw in {"1", "true", "yes", "on"}:
                return True
            if raw in {"0", "false", "no", "off"}:
                return False
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, list):
        raw = value
    else:
        raw = []
    return [str(item or "").strip() for item in raw if str(item or "").strip()]


_SESSION_MANAGER = IsolatedDesktopProviderSessionManager()
