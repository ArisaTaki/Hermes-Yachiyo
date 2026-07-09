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
from apps.shell.yachiyo_agent.desktop_provider_contract import (
    OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    virtual_desktop_provider_conformance_summary,
    virtual_desktop_provider_contract_evidence,
    virtual_desktop_provider_manifest_contract_evidence,
)
from apps.shell.yachiyo_agent.desktop_execution_policy import (
    is_local_low_risk_foreground_tool,
    is_user_foreground_takeover_tool,
    local_low_risk_foreground_tool_allowed,
    user_foreground_takeover_allowed,
)
from apps.shell.yachiyo_agent.contracts import TaskCoreSnapshot
from apps.shell.yachiyo_agent.task_progress_snapshots import (
    task_progress_summary_from_task_core,
)
from packages.security import redact_api_error_text

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
    "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND",
    "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK",
    "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE",
    "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND",
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
    "real_virtual_desktop_provider_required",
}

_PROVIDER_START_BLOCKERS = {
    "sandbox_desktop_provider_required",
    "sandbox_keyboard_mouse_provider_required",
    "sandbox_desktop_session_required",
    "sandbox_desktop_adapter_required",
    "isolated_desktop_provider_required",
    "loopback_desktop_backend",
    "desktop_backend_not_release_ready",
    "real_virtual_desktop_backend_required",
}

_REAL_VIRTUAL_BACKEND_REQUIRED_STATUSES = {
    "real_virtual_desktop_provider_required",
    "virtual_desktop_provider_contract_required",
}

_REAL_VIRTUAL_BACKEND_BLOCKERS = {
    "loopback_desktop_backend",
    "desktop_backend_not_release_ready",
    "real_virtual_desktop_backend_required",
}


class IsolatedDesktopProviderSessionManager:
    """Starts, stops, and probes a local isolated desktop provider process."""

    def __init__(self, *, repo_root: Path | None = None) -> None:
        self._repo_root = repo_root or Path(__file__).resolve().parents[3]
        self._process: subprocess.Popen[str] | None = None
        self._env: dict[str, str] = {}
        self._command: list[str] = []
        self._provider_manifest_evidence: dict[str, Any] = {}
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
                self._provider_manifest_evidence = {}
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
            provider_contract = _provider_contract_evidence_for_status(
                provider_status,
            )
            provider_conformance = _provider_conformance_for_status(
                provider_status,
                provider_contract=provider_contract,
                mode="session_manager_provider_contract_check",
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
                "provider_contract": provider_contract,
                "provider_manifest_evidence": dict(
                    self._provider_manifest_evidence
                ),
                "provider_conformance": provider_conformance,
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
            self._provider_manifest_evidence = {}
            self._source = "isolated_provider_session_manager"
            self._started_at = time.time()
            _apply_runtime_env(env)
            return {**self.status(probe_health=True), "started": True, "launch": launch}

    def start_managed_external(
        self,
        *,
        tools: list[str] | None = None,
        timeout_seconds: float = 10.0,
        requires_real_virtual_desktop_backend: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            current = self.status(probe_health=True)
            if current["running"]:
                return {**current, "started": False}
            manifest: dict[str, Any] = {}
            command: list[str] = []
            start_cwd = self._repo_root
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
            failure_request = {
                "tools": requested_tools,
                "requires_real_virtual_desktop_backend": (
                    requires_real_virtual_desktop_backend
                ),
            }
            try:
                manifest = _managed_external_provider_manifest(self._repo_root)
                manifest_evidence = _provider_manifest_evidence_for_manifest(
                    manifest
                )
                command = _managed_external_provider_start_command(
                    self._repo_root,
                    manifest=manifest,
                )
                if not command:
                    raise RuntimeError(
                        "desktop provider start command is not configured"
                    )
                start_cwd = _managed_external_provider_start_cwd(
                    self._repo_root,
                    manifest=manifest,
                )
                process = subprocess.Popen(
                    command,
                    cwd=str(start_cwd),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=start_env,
                )
            except Exception as exc:
                return _managed_external_provider_start_failed_status(
                    failure_request,
                    exc,
                    repo_root=self._repo_root,
                    manifest=manifest,
                    command=command,
                    start_cwd=start_cwd,
                    timeout_seconds=timeout_seconds,
                )
            try:
                launch = _read_launch_payload(
                    process,
                    timeout_seconds=timeout_seconds,
                    label="managed desktop provider",
                )
            except Exception as exc:
                _terminate_process(process)
                return _managed_external_provider_start_failed_status(
                    failure_request,
                    exc,
                    repo_root=self._repo_root,
                    manifest=manifest,
                    command=command,
                    start_cwd=start_cwd,
                    timeout_seconds=timeout_seconds,
                )
            env = _runtime_env_from_launch(_merge_manifest_launch(manifest, launch))
            self._process = process
            self._command = command
            self._env = env
            self._provider_manifest_evidence = manifest_evidence
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
            self._provider_manifest_evidence = {}
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
    requires_real_backend = _optional_bool(
        payload.get("requires_real_virtual_desktop_backend"),
        payload.get("require_real_virtual_desktop_backend"),
        payload.get("real_virtual_desktop_backend_required"),
    ) is True
    external_status = _external_isolated_desktop_provider_session_status()
    if bool(external_status.get("running")) and _session_status_supports_targets(
        external_status,
        [{"request_id": "", "tool_name": tool} for tool in clean_tools or []],
    ):
        if requires_real_backend and not _session_status_uses_real_virtual_backend(
            external_status
        ):
            return _real_virtual_desktop_provider_required_status(
                payload,
                current_status=external_status,
            )
        return {**external_status, "started": False}
    if _managed_external_provider_start_configured():
        started = _SESSION_MANAGER.start_managed_external(
            tools=clean_tools,
            requires_real_virtual_desktop_backend=requires_real_backend,
        )
        if bool(started.get("ok")) is False:
            return started
        if requires_real_backend and not _session_status_uses_real_virtual_backend(
            started
        ):
            return _real_virtual_desktop_provider_required_status(
                payload,
                current_status=started,
            )
        return started
    if requires_real_backend:
        return _real_virtual_desktop_provider_required_status(
            payload,
            current_status=external_status,
        )
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
    requires_real_backend = _envelope_requires_real_virtual_backend(
        envelope,
        scoped_targets,
    )
    status = isolated_desktop_provider_session_status()
    base = {
        "ok": True,
        "needed": bool(targets),
        "auto_start": bool(auto_start),
        "started": False,
        "requires_real_virtual_desktop_backend": requires_real_backend,
        "request_ids": [target["request_id"] for target in scoped_targets],
        "tool_names": sorted({target["tool_name"] for target in scoped_targets}),
        "reason": "isolated_provider_required" if targets else "",
        "source": "isolated_provider_session_manager",
    }
    if not targets:
        return _session_not_needed_status(base, status)
    if bool(status.get("running")) and _session_status_supports_targets(
        status,
        scoped_targets,
    ):
        if requires_real_backend and not _session_status_uses_real_virtual_backend(
            status
        ):
            required_status = _real_virtual_desktop_provider_required_status(
                {
                    "tools": base["tool_names"],
                    "requires_real_virtual_desktop_backend": True,
                },
                current_status=status,
            )
            return {
                **_session_status_with_base(base, required_status),
                "ok": False,
                "running": bool(required_status.get("running")),
            }
        return {**_session_status_with_base(base, status), "running": True}
    if bool(status.get("running")):
        return {
            **_session_status_with_base(base, status),
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
            **_session_status_with_base(base, status),
            "ok": False,
            "running": False,
            "reason": "external_isolated_provider_unavailable",
        }
    if not auto_start:
        return _session_status_with_base(base, status)
    try:
        start_request: dict[str, Any] = {
            "tools": sorted({target["tool_name"] for target in scoped_targets})
        }
        if requires_real_backend:
            start_request["requires_real_virtual_desktop_backend"] = True
        started = start_isolated_desktop_provider_session(start_request)
    except Exception as exc:
        return {
            **base,
            "ok": False,
            "status": "start_failed",
            "running": False,
            "error": redact_api_error_text(exc),
        }
    return {
        **_session_status_with_base(base, started),
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
    payload = _envelope_with_desktop_provider_task_progress(
        payload,
        public_session,
    )
    return payload


def _envelope_with_desktop_provider_task_progress(
    envelope: dict[str, Any],
    session: dict[str, Any],
) -> dict[str, Any]:
    task_core_payload = envelope.get("task_core")
    if not isinstance(task_core_payload, dict):
        return envelope
    try:
        task_core = TaskCoreSnapshot.model_validate(task_core_payload)
    except ValueError:
        return envelope
    task_progress = task_progress_summary_from_task_core(
        task_core,
        desktop_provider_session=session,
    )
    if task_progress is None:
        return envelope
    existing_progress = (
        dict(envelope.get("task_progress"))
        if isinstance(envelope.get("task_progress"), dict)
        else {}
    )
    progress_payload = task_progress.model_dump(mode="json")
    if existing_progress:
        progress_payload = {
            **existing_progress,
            **{
                key: progress_payload[key]
                for key in (
                    "status",
                    "needs_user_action",
                    "needs_replan",
                    "desktop_provider_session_status",
                    "desktop_provider_session_needed",
                    "desktop_provider_session_running",
                    "desktop_provider_session_started",
                    "desktop_provider_session_provider_id",
                    "desktop_provider_session_tool_names",
                    "desktop_provider_session_needs_user_action",
                    "desktop_provider_session_needs_replan",
                    "progress_text",
                )
                if key in progress_payload
            },
        }
    return {**envelope, "task_progress": progress_payload}


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
        detail = redact_api_error_text(stderr)
        message = f"{label} exited early"
        raise RuntimeError(f"{message}: {detail}" if detail else message)
    try:
        payload = json.loads(str(line or "{}"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} reported invalid launch status JSON") from exc
    if not isinstance(payload, dict) or not payload.get("ok"):
        detail = redact_api_error_text(
            (payload.get("error") or payload.get("message"))
            if isinstance(payload, dict)
            else ""
        )
        message = f"{label} launch failed"
        raise RuntimeError(f"{message}: {detail}" if detail else message)
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
        "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND": "desktop_backend_kind",
        "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK": (
            "desktop_backend_is_loopback"
        ),
        "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE": (
            "desktop_backend_ready_for_public_release"
        ),
        "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND": (
            "requires_real_virtual_desktop_backend"
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
        "keyboard_mouse_capture_supported",
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
    provider_manifest_evidence: dict[str, Any] = {}
    manifest_payload: dict[str, Any] = {}
    if str(os.environ.get(_PROVIDER_MANIFEST_ENV) or "").strip():
        try:
            manifest_payload = _managed_external_provider_manifest(
                _SESSION_MANAGER._repo_root
            )
            provider_manifest_evidence = _provider_manifest_evidence_for_manifest(
                manifest_payload
            )
        except Exception:
            manifest_payload = {}
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
            manifest = manifest_payload or _managed_external_provider_manifest(
                _SESSION_MANAGER._repo_root
            )
            if not provider_manifest_evidence:
                provider_manifest_evidence = _provider_manifest_evidence_for_manifest(
                    manifest
                )
            manifest_env = _runtime_env_from_launch(manifest)
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
    provider_contract = _provider_contract_evidence_for_status(provider_status)
    provider_conformance = _provider_conformance_for_status(
        provider_status,
        provider_contract=provider_contract,
        mode="external_provider_contract_check",
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
        "desktop_session_kind": str(provider_status.get("desktop_session_kind") or ""),
        "desktop_session_isolated": _optional_bool(
            provider_status.get("desktop_session_isolated")
        ),
        "foreground_takeover_required": _optional_bool(
            provider_status.get("foreground_takeover_required")
        ),
        "keyboard_mouse_capture_supported": _optional_bool(
            provider_status.get("keyboard_mouse_capture_supported")
        ),
        "desktop_backend_kind": str(provider_status.get("desktop_backend_kind") or ""),
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
        "provider_contract": provider_contract,
        "provider_manifest_evidence": provider_manifest_evidence,
        "provider_conformance": provider_conformance,
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


def _envelope_requires_real_virtual_backend(
    envelope: dict[str, Any] | None,
    targets: list[dict[str, str]],
) -> bool:
    if not isinstance(envelope, dict):
        return False
    target_ids = {
        str(target.get("request_id") or "").strip()
        for target in targets
        if str(target.get("request_id") or "").strip()
    }
    requests = envelope.get("requests")
    if not isinstance(requests, list):
        return False
    for index, request in enumerate(requests, start=1):
        if not isinstance(request, dict):
            continue
        tool_name = _request_tool_name(request)
        request_id = str(
            request.get("request_id") or f"request:{index}:{tool_name}"
        ).strip()
        if target_ids and request_id not in target_ids:
            continue
        if _request_requires_real_virtual_backend(request):
            return True
    return False


def _request_requires_real_virtual_backend(request: dict[str, Any]) -> bool:
    policy = _mapping(request.get("desktop_execution_policy"))
    if str(policy.get("source") or "").strip() == "agent_studio":
        return True
    sources = (
        request,
        _mapping(request.get("desktop_execution_route")),
        _mapping(request.get("sandbox_provider")),
        _mapping(request.get("desktop_provider_session")),
    )
    for source in sources:
        if not source:
            continue
        if (
            _optional_bool(source.get("requires_real_virtual_desktop_backend"))
            is True
        ):
            return True
        if str(source.get("status") or "").strip() in (
            _REAL_VIRTUAL_BACKEND_REQUIRED_STATUSES
        ):
            return True
        blockers = set(_string_list(source.get("blocking_conditions")))
        blockers.update(
            _string_list(source.get("provider_contract_blocking_conditions"))
        )
        provider_contract = _mapping(source.get("provider_contract"))
        blockers.update(_string_list(provider_contract.get("blocking_conditions")))
        if blockers & _REAL_VIRTUAL_BACKEND_BLOCKERS:
            return True
    return False


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
    if _request_uses_ready_local_low_risk_foreground_route(
        tool_name,
        request=request,
        route=route,
        provider=provider,
    ):
        return False
    policy = _mapping(request.get("desktop_execution_policy"))
    if (
        is_local_low_risk_foreground_tool(tool_name)
        and _policy_prefers_isolated_foreground(policy)
    ):
        return True
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
    if _policy_prefers_isolated_foreground(policy):
        return True
    return False


def _request_uses_ready_local_low_risk_foreground_route(
    tool_name: str,
    *,
    request: dict[str, Any],
    route: dict[str, Any],
    provider: dict[str, Any],
) -> bool:
    if not local_low_risk_foreground_tool_allowed(tool_name, request):
        return False
    provider_kind = str(
        route.get("selected_provider_kind")
        or route.get("provider_kind")
        or provider.get("provider_kind")
        or ""
    ).strip()
    if provider_kind != "local_desktop":
        return False
    if str(route.get("status") or "").strip() not in {
        "provider_ready",
        "ready",
        "supervised_live",
    }:
        return False
    return bool(route.get("can_execute", True))


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


def _session_status_with_base(
    base: dict[str, Any],
    status: dict[str, Any],
) -> dict[str, Any]:
    payload = {**base, **_public_session_status(status)}
    if base.get("requires_real_virtual_desktop_backend") is True:
        payload["requires_real_virtual_desktop_backend"] = True
    return payload


def _session_not_needed_status(
    base: dict[str, Any],
    status: dict[str, Any],
) -> dict[str, Any]:
    payload = _session_status_with_base(base, status)
    payload.update(
        {
            "ok": True,
            "needed": False,
            "status": "not_needed",
            "running": False,
            "started": False,
            "requires_real_virtual_desktop_backend": False,
            "reason": "",
            "request_ids": [],
            "tool_names": [],
            "blocking_conditions": [],
            "provider_contract": {},
            "provider_conformance": {},
        }
    )
    return payload


def _provider_contract_evidence_for_status(status: dict[str, Any]) -> dict[str, Any]:
    provider_status = _mapping(status.get("provider_status"))
    source = dict(provider_status or status)
    for key in (
        "provider_id",
        "desktop_session_kind",
        "desktop_session_isolated",
        "foreground_takeover_required",
        "desktop_backend_kind",
        "desktop_backend_is_loopback",
        "desktop_backend_ready_for_public_release",
        "requires_real_virtual_desktop_backend",
        "supported_tools",
    ):
        if source.get(key) in (None, "", [], {}) and status.get(key) not in (
            None,
            "",
            [],
            {},
        ):
            source[key] = status.get(key)
    source.setdefault(
        "configured",
        bool(source.get("configured"))
        or bool(source.get("provider_id"))
        or bool(status.get("provider_id")),
    )
    source.setdefault(
        "available",
        bool(source.get("available")) or bool(status.get("running")),
    )
    source.setdefault(
        "adapter_ready",
        bool(source.get("adapter_ready")) or bool(status.get("running")),
    )
    return virtual_desktop_provider_contract_evidence(
        source,
        required_tools=OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    )


def _provider_conformance_for_status(
    status: dict[str, Any],
    *,
    provider_contract: dict[str, Any] | None = None,
    mode: str = "session_provider_contract_check",
    runtime_checked: bool | None = None,
    release_candidate: bool | None = None,
    public_release_ready: bool | None = None,
) -> dict[str, Any]:
    provider_status = _mapping(status.get("provider_status"))
    source = {**provider_status, **status}
    contract = provider_contract or _provider_contract_evidence_for_status(status)
    return virtual_desktop_provider_conformance_summary(
        contract,
        status=source,
        mode=mode,
        runtime_checked=bool(provider_status or status)
        if runtime_checked is None
        else runtime_checked,
        release_candidate=release_candidate,
        public_release_ready=public_release_ready,
        supported_tools=_string_list(
            status.get("supported_tools") or provider_status.get("supported_tools")
        ),
    )


def _provider_manifest_evidence_for_manifest(
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(manifest, dict) or not manifest:
        return {}
    return virtual_desktop_provider_manifest_contract_evidence(
        manifest,
        required_tools=OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    )


def _managed_external_provider_start_failed_status(
    request: dict[str, Any],
    exc: Exception,
    *,
    repo_root: Path,
    manifest: dict[str, Any] | None = None,
    command: list[str] | None = None,
    start_cwd: Path | None = None,
    timeout_seconds: float = 0.0,
) -> dict[str, Any]:
    manifest_payload = _provider_runtime_payload(manifest or {})
    provider_manifest_evidence = _provider_manifest_evidence_for_manifest(
        manifest or {}
    )
    requires_real_backend = (
        _optional_bool(
            request.get("requires_real_virtual_desktop_backend"),
            request.get("require_real_virtual_desktop_backend"),
            request.get("real_virtual_desktop_backend_required"),
        )
        is True
    )
    source = {
        **manifest_payload,
        "configured": True,
        "available": False,
        "adapter_ready": False,
        "status": "start_failed",
    }
    if requires_real_backend and source.get(
        "requires_real_virtual_desktop_backend"
    ) in (None, "", [], {}):
        source["requires_real_virtual_desktop_backend"] = True
    reported_requires_real_backend = (
        requires_real_backend
        or _optional_bool(source.get("requires_real_virtual_desktop_backend")) is True
    )
    provider_id = str(
        source.get("provider_id")
        or request.get("provider_id")
        or "managed-external-desktop"
    ).strip()
    source["provider_id"] = provider_id
    blockers = _string_list(source.get("blocking_conditions"))
    for blocker in (
        "managed_external_provider_start_failed",
        "configured_virtual_desktop_provider_start_failed",
    ):
        if blocker not in blockers:
            blockers.append(blocker)
    source["blocking_conditions"] = blockers
    provider_contract = dict(_provider_contract_evidence_for_status(source))
    contract_blockers = _string_list(provider_contract.get("blocking_conditions"))
    for blocker in blockers:
        if blocker not in contract_blockers:
            contract_blockers.append(blocker)
    provider_contract["ok"] = False
    provider_contract["blocking_conditions"] = contract_blockers
    provider_conformance = _provider_conformance_for_status(
        source,
        provider_contract=provider_contract,
        mode="managed_external_provider_start_check",
        runtime_checked=False,
        release_candidate=False,
        public_release_ready=False,
    )
    manifest_path = _managed_external_provider_manifest_path(repo_root)
    clean_command = [redact_api_error_text(item) for item in command or []]
    return {
        "ok": False,
        "status": "start_failed",
        "running": False,
        "started": False,
        "provider_id": provider_id,
        "reason": "managed_external_provider_start_failed",
        "error": redact_api_error_text(exc),
        "blocking_conditions": contract_blockers,
        "desktop_session_kind": str(source.get("desktop_session_kind") or ""),
        "desktop_session_isolated": _optional_bool(
            source.get("desktop_session_isolated")
        ),
        "foreground_takeover_required": _optional_bool(
            source.get("foreground_takeover_required")
        ),
        "keyboard_mouse_capture_supported": _optional_bool(
            source.get("keyboard_mouse_capture_supported")
        ),
        "desktop_backend_kind": str(source.get("desktop_backend_kind") or ""),
        "desktop_backend_is_loopback": _optional_bool(
            source.get("desktop_backend_is_loopback")
        ),
        "desktop_backend_ready_for_public_release": _optional_bool(
            source.get("desktop_backend_ready_for_public_release")
        ),
        "requires_real_virtual_desktop_backend": reported_requires_real_backend,
        "supported_tools": _string_list(source.get("supported_tools")),
        "provider_status": source,
        "provider_contract": provider_contract,
        "provider_manifest_evidence": provider_manifest_evidence,
        "provider_conformance": provider_conformance,
        "command": clean_command,
        "manifest_path": str(manifest_path or ""),
        "start_cwd": str(start_cwd or ""),
        "timeout_seconds": float(timeout_seconds or 0.0),
        "source": "managed_external_provider_session",
        "external_provider_configured": True,
    }


def _public_session_status(status: dict[str, Any]) -> dict[str, Any]:
    provider_status = _mapping(status.get("provider_status"))
    provider_contract = (
        _mapping(status.get("provider_contract"))
        if "provider_contract" in status
        else _mapping(provider_status.get("provider_contract"))
        or _provider_contract_evidence_for_status(status)
    )
    provider_conformance = (
        _mapping(status.get("provider_conformance"))
        if "provider_conformance" in status
        else _mapping(provider_status.get("provider_conformance"))
        or _provider_conformance_for_status(
            status,
            provider_contract=provider_contract,
        )
    )
    provider_manifest_evidence = _mapping(
        status.get("provider_manifest_evidence")
        or provider_status.get("provider_manifest_evidence")
    )
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
        "blocking_conditions": _string_list(
            status.get("blocking_conditions")
            or provider_status.get("blocking_conditions")
        ),
        "supported_tools": _string_list(
            status.get("supported_tools") or provider_status.get("supported_tools")
        ),
        "provider_contract": provider_contract,
        "provider_manifest_evidence": provider_manifest_evidence,
        "provider_conformance": provider_conformance,
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


def _session_status_uses_real_virtual_backend(status: dict[str, Any]) -> bool:
    provider_status = _mapping(status.get("provider_status"))
    provider_contract = _mapping(
        status.get("provider_contract") or provider_status.get("provider_contract")
    ) or _provider_contract_evidence_for_status(status)
    backend_kind = str(
        status.get("desktop_backend_kind")
        or provider_status.get("desktop_backend_kind")
        or ""
    ).strip()
    backend_is_loopback = _optional_bool(
        status.get("desktop_backend_is_loopback"),
        provider_status.get("desktop_backend_is_loopback"),
    )
    backend_release_ready = _optional_bool(
        status.get("desktop_backend_ready_for_public_release"),
        provider_status.get("desktop_backend_ready_for_public_release"),
    )
    requires_real_backend = _optional_bool(
        status.get("requires_real_virtual_desktop_backend"),
        provider_status.get("requires_real_virtual_desktop_backend"),
    )
    session_kind = str(
        status.get("desktop_session_kind")
        or provider_status.get("desktop_session_kind")
        or ""
    ).strip()
    session_isolated = _optional_bool(
        status.get("desktop_session_isolated"),
        provider_status.get("desktop_session_isolated"),
    )
    return bool(
        provider_contract.get("ok") is True
        and backend_kind
        and backend_is_loopback is False
        and backend_release_ready is True
        and requires_real_backend is False
        and (
            session_isolated is True
            or session_kind in {"isolated_desktop", "virtual_desktop"}
        )
    )


def _real_virtual_desktop_provider_required_status(
    request: dict[str, Any],
    *,
    current_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = dict(current_status or {})
    provider_status = _mapping(status.get("provider_status"))
    provider_id = str(
        status.get("provider_id")
        or provider_status.get("provider_id")
        or request.get("provider_id")
        or "real-virtual-desktop"
    ).strip()
    blockers = _string_list(status.get("blocking_conditions"))
    backend_is_loopback = _optional_bool(
        status.get("desktop_backend_is_loopback"),
        provider_status.get("desktop_backend_is_loopback"),
    )
    backend_release_ready = _optional_bool(
        status.get("desktop_backend_ready_for_public_release"),
        provider_status.get("desktop_backend_ready_for_public_release"),
    )
    provider_contract = _mapping(
        status.get("provider_contract") or provider_status.get("provider_contract")
    ) or _provider_contract_evidence_for_status(status)
    if backend_is_loopback is True and "loopback_desktop_backend" not in blockers:
        blockers.append("loopback_desktop_backend")
    if (
        backend_release_ready is False
        and "desktop_backend_not_release_ready" not in blockers
    ):
        blockers.append("desktop_backend_not_release_ready")
    for blocker in _string_list(provider_contract.get("blocking_conditions")):
        if blocker not in blockers:
            blockers.append(blocker)
    for blocker in (
        "configured_virtual_desktop_provider_required",
        "real_virtual_desktop_backend_required",
    ):
        if blocker not in blockers:
            blockers.append(blocker)
    provider_conformance = _mapping(
        status.get("provider_conformance")
        or provider_status.get("provider_conformance")
    ) or _provider_conformance_for_status(
        status,
        provider_contract=provider_contract,
        release_candidate=False,
        public_release_ready=False,
    )
    return {
        **status,
        "ok": False,
        "status": "real_virtual_desktop_provider_required",
        "running": bool(status.get("running")),
        "started": bool(status.get("started")),
        "provider_id": provider_id,
        "reason": (
            "A real non-loopback virtual desktop provider is required before "
            "desktop app execution can continue."
        ),
        "blocking_conditions": blockers,
        "desktop_backend_kind": str(
            status.get("desktop_backend_kind")
            or provider_status.get("desktop_backend_kind")
            or ""
        ),
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
        "desktop_backend_is_loopback": backend_is_loopback,
        "desktop_backend_ready_for_public_release": backend_release_ready,
        "requires_real_virtual_desktop_backend": True,
        "provider_contract": provider_contract,
        "provider_conformance": provider_conformance,
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
