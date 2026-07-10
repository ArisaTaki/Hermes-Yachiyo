"""Host-side SSH tunnel and lifecycle bridge for a macOS VM guest provider."""

from __future__ import annotations

import argparse
import json
import os
import queue
import shlex
import signal
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request

from apps.core.tls import urlopen_with_bundled_ca
from apps.shell.agent.runtime.virtual_desktop_guest_provider import (
    DEFAULT_BACKEND_KIND,
    DEFAULT_PROVIDER_ID,
)
from apps.shell.yachiyo_agent.desktop_provider_contract import (
    virtual_desktop_provider_manifest_template,
)
from packages.security import redact_api_error_text, scrubbed_subprocess_env

DEFAULT_LOCAL_HOST = "127.0.0.1"
DEFAULT_LOCAL_PORT = 29097
DEFAULT_GUEST_PORT = 29097
DEFAULT_REMOTE_PYTHON = "python3"
DEFAULT_REMOTE_PROVIDER_SCRIPT = "scripts/run_virtual_desktop_guest_provider.py"
DEFAULT_REMOTE_GUEST_MARKER = (
    "~/Library/Application Support/Oha-Yachiyo/virtual-desktop-guest.json"
)
DEFAULT_REMOTE_TOKEN_FILE = (
    "~/Library/Application Support/Oha-Yachiyo/desktop-provider.token"
)


@dataclass(frozen=True)
class SshVirtualDesktopBridgeConfig:
    ssh_target: str
    remote_repo: str
    session_id: str
    guest_marker: str = DEFAULT_REMOTE_GUEST_MARKER
    guest_token_file: str = DEFAULT_REMOTE_TOKEN_FILE
    local_host: str = DEFAULT_LOCAL_HOST
    local_port: int = DEFAULT_LOCAL_PORT
    guest_port: int = DEFAULT_GUEST_PORT
    provider_id: str = DEFAULT_PROVIDER_ID
    remote_python: str = DEFAULT_REMOTE_PYTHON
    remote_provider_script: str = DEFAULT_REMOTE_PROVIDER_SCRIPT
    identity_file: str = ""
    ssh_options: tuple[str, ...] = ()


def ssh_virtual_desktop_command(
    config: SshVirtualDesktopBridgeConfig,
) -> list[str]:
    _validate_config(config)
    remote_script = _remote_path(config.remote_repo, config.remote_provider_script)
    remote_command = " ".join(
        shlex.quote(value)
        for value in (
            config.remote_python,
            remote_script,
            "--host",
            "127.0.0.1",
            "--port",
            str(config.guest_port),
            "--provider-id",
            config.provider_id,
            "--session-id",
            config.session_id,
            "--guest-marker",
            config.guest_marker,
            "--token-file",
            config.guest_token_file,
            "--quiet",
        )
    )
    command = [
        "ssh",
        "-T",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        "-o",
        "ForwardAgent=no",
        "-L",
        (
            f"{config.local_host}:{config.local_port}:"
            f"127.0.0.1:{config.guest_port}"
        ),
    ]
    if config.identity_file:
        command.extend(["-i", str(Path(config.identity_file).expanduser())])
    for option in config.ssh_options:
        command.extend(["-o", str(option)])
    command.extend([config.ssh_target, remote_command])
    return command


def ssh_virtual_desktop_provider_manifest(
    config: SshVirtualDesktopBridgeConfig,
) -> dict[str, Any]:
    _validate_config(config)
    base_url = f"http://{config.local_host}:{config.local_port}"
    payload = virtual_desktop_provider_manifest_template(
        provider_id=config.provider_id,
        base_url=base_url,
    )
    payload.update(
        {
            "desktop_backend_kind": DEFAULT_BACKEND_KIND,
            "entrypoint": {
                "script": "scripts/run_ssh_virtual_desktop_provider.py",
                "args": _manifest_entrypoint_args(config),
                "cwd": ".",
                "launch_timeout_seconds": 45,
            },
            "ssh_bridge": {
                "ssh_target": config.ssh_target,
                "remote_repo": config.remote_repo,
                "remote_provider_script": config.remote_provider_script,
                "local_host": config.local_host,
                "local_port": config.local_port,
                "guest_port": config.guest_port,
                "guest_marker": config.guest_marker,
                "guest_token_file": config.guest_token_file,
                "credentials_forwarded": False,
            },
        }
    )
    safety = dict(payload.get("safety") or {})
    safety["desktop_backend_kind"] = DEFAULT_BACKEND_KIND
    payload["safety"] = safety
    return payload


def run_ssh_virtual_desktop_bridge(
    config: SshVirtualDesktopBridgeConfig,
    *,
    launch_timeout_seconds: float = 30.0,
    popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> int:
    command = ssh_virtual_desktop_command(config)
    process = popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=_ssh_subprocess_env(),
    )
    stderr_tail: deque[str] = deque(maxlen=20)
    stderr_thread = threading.Thread(
        target=_drain_stream,
        args=(process.stderr, stderr_tail),
        daemon=True,
    )
    stderr_thread.start()
    try:
        launch = _read_launch_payload(
            process,
            timeout_seconds=launch_timeout_seconds,
            stderr_tail=stderr_tail,
        )
        public_launch = ssh_bridge_launch_payload(config, launch)
        host_token = str(
            os.environ.get("OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN") or ""
        ).strip()
        status = authenticated_ssh_bridge_status(
            config,
            token=host_token,
        )
        bridge_status = dict(public_launch.get("ssh_bridge") or {})
        bridge_status["authenticated_status_verified"] = True
        public_launch["ssh_bridge"] = bridge_status
        public_launch["authentication_configured"] = bool(
            status.get("authentication_configured")
        )
        print(
            json.dumps(public_launch, ensure_ascii=False, sort_keys=True),
            flush=True,
        )
        stdout_thread = threading.Thread(
            target=_drain_stream,
            args=(process.stdout, deque(maxlen=1)),
            daemon=True,
        )
        stdout_thread.start()
        return _wait_with_signal_forwarding(process)
    except Exception:
        _terminate_process(process)
        raise


def ssh_bridge_launch_payload(
    config: SshVirtualDesktopBridgeConfig,
    remote_launch: dict[str, Any],
) -> dict[str, Any]:
    if remote_launch.get("ok") is not True:
        raise RuntimeError("virtual desktop guest provider launch failed")
    if remote_launch.get("desktop_session_isolated") is not True:
        raise RuntimeError("virtual desktop guest provider is not isolated")
    if remote_launch.get("foreground_takeover_required") is not False:
        raise RuntimeError("virtual desktop guest provider requires foreground takeover")
    if remote_launch.get("desktop_backend_is_loopback") is not False:
        raise RuntimeError("virtual desktop guest provider reported loopback backend")
    if remote_launch.get("desktop_backend_ready_for_public_release") is not True:
        raise RuntimeError("virtual desktop guest provider is not release-ready")
    if remote_launch.get("requires_real_virtual_desktop_backend") is not False:
        raise RuntimeError("virtual desktop guest provider still requires a real backend")
    if str(remote_launch.get("provider_id") or "").strip() != config.provider_id:
        raise RuntimeError("virtual desktop guest provider id mismatch")
    if "idempotent_tool_requests" not in {
        str(item or "").strip()
        for item in remote_launch.get("capabilities", [])
    }:
        raise RuntimeError("virtual desktop guest provider lacks idempotent requests")
    base_url = f"http://{config.local_host}:{config.local_port}"
    return {
        **remote_launch,
        "provider_id": config.provider_id,
        "url": base_url,
        "status_url": f"{base_url}/status",
        "execute_url": f"{base_url}/tools/execute",
        "allow_remote": False,
        "source": "ssh_virtual_desktop_bridge",
        "ssh_bridge": {
            "ssh_target": config.ssh_target,
            "local_host": config.local_host,
            "local_port": config.local_port,
            "guest_port": config.guest_port,
            "credentials_forwarded": False,
        },
    }


def authenticated_ssh_bridge_status(
    config: SshVirtualDesktopBridgeConfig,
    *,
    token: str,
    timeout_seconds: float = 5.0,
    urlopen: Callable[..., Any] = urlopen_with_bundled_ca,
) -> dict[str, Any]:
    clean_token = str(token or "").strip()
    if not clean_token:
        raise RuntimeError("host desktop provider token is not configured")
    request = Request(
        f"http://{config.local_host}:{config.local_port}/status",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {clean_token}",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=max(0.1, float(timeout_seconds))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"authenticated virtual desktop status probe failed: {redact_api_error_text(exc)}"
        ) from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError("authenticated virtual desktop status probe was not ready")
    if str(payload.get("provider_id") or "").strip() != config.provider_id:
        raise RuntimeError("authenticated virtual desktop status provider id mismatch")
    if payload.get("authentication_configured") is not True:
        raise RuntimeError("virtual desktop provider did not confirm authentication")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = _config_from_args(args)
    if args.manifest:
        print(
            json.dumps(
                ssh_virtual_desktop_provider_manifest(config),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    try:
        return run_ssh_virtual_desktop_bridge(
            config,
            launch_timeout_seconds=args.launch_timeout_seconds,
        )
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": redact_api_error_text(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        return 2


def _manifest_entrypoint_args(config: SshVirtualDesktopBridgeConfig) -> list[str]:
    args = [
        "--ssh-target",
        config.ssh_target,
        "--remote-repo",
        config.remote_repo,
        "--session-id",
        config.session_id,
        "--guest-marker",
        config.guest_marker,
        "--guest-token-file",
        config.guest_token_file,
        "--local-host",
        config.local_host,
        "--local-port",
        str(config.local_port),
        "--guest-port",
        str(config.guest_port),
        "--provider-id",
        config.provider_id,
        "--remote-python",
        config.remote_python,
        "--remote-provider-script",
        config.remote_provider_script,
    ]
    if config.identity_file:
        args.extend(["--identity-file", config.identity_file])
    for option in config.ssh_options:
        args.extend(["--ssh-option", option])
    return args


def _config_from_args(args: argparse.Namespace) -> SshVirtualDesktopBridgeConfig:
    return SshVirtualDesktopBridgeConfig(
        ssh_target=args.ssh_target,
        remote_repo=args.remote_repo,
        session_id=args.session_id,
        guest_marker=args.guest_marker,
        guest_token_file=args.guest_token_file,
        local_host=args.local_host,
        local_port=args.local_port,
        guest_port=args.guest_port,
        provider_id=args.provider_id,
        remote_python=args.remote_python,
        remote_provider_script=args.remote_provider_script,
        identity_file=args.identity_file,
        ssh_options=tuple(args.ssh_option),
    )


def _read_launch_payload(
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float,
    stderr_tail: deque[str],
) -> dict[str, Any]:
    output: queue.Queue[str] = queue.Queue(maxsize=1)

    def read_line() -> None:
        if process.stdout is not None:
            output.put(process.stdout.readline())

    thread = threading.Thread(target=read_line, daemon=True)
    thread.start()
    try:
        line = output.get(timeout=max(0.1, float(timeout_seconds)))
    except queue.Empty as exc:
        raise RuntimeError("virtual desktop SSH bridge launch timed out") from exc
    if not line:
        detail = redact_api_error_text("\n".join(stderr_tail))
        message = "virtual desktop SSH bridge exited before launch"
        raise RuntimeError(f"{message}: {detail}" if detail else message)
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise RuntimeError("virtual desktop SSH bridge received invalid launch JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("virtual desktop SSH bridge launch payload must be an object")
    return payload


def _wait_with_signal_forwarding(process: subprocess.Popen[str]) -> int:
    previous_handlers: dict[int, Any] = {}

    def forward(signum: int, _frame: Any) -> None:
        if process.poll() is None:
            process.send_signal(signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, forward)
    try:
        return int(process.wait())
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _drain_stream(stream: Any, tail: deque[str]) -> None:
    if stream is None:
        return
    for line in stream:
        clean = str(line or "").rstrip()
        if clean:
            tail.append(clean)


def _ssh_subprocess_env() -> dict[str, str]:
    env = scrubbed_subprocess_env()
    ssh_auth_sock = str(os.environ.get("SSH_AUTH_SOCK") or "").strip()
    if ssh_auth_sock:
        env["SSH_AUTH_SOCK"] = ssh_auth_sock
    return env


def _remote_path(repo: str, value: str) -> str:
    clean = str(value or "").strip()
    if clean.startswith("/"):
        return clean
    return f"{str(repo or '').rstrip('/')}/{clean.lstrip('/')}"


def _validate_config(config: SshVirtualDesktopBridgeConfig) -> None:
    if not config.ssh_target or config.ssh_target.startswith("-"):
        raise ValueError("SSH target is required and must not start with '-'")
    if not config.remote_repo:
        raise ValueError("remote repo path is required")
    if not config.remote_repo.startswith("/"):
        raise ValueError("remote repo path must be absolute")
    if not config.session_id:
        raise ValueError("virtual desktop session id is required")
    if config.local_host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("SSH bridge local host must be loopback")
    for label, value in (("local port", config.local_port), ("guest port", config.guest_port)):
        if not 1 <= int(value) <= 65535:
            raise ValueError(f"{label} must be between 1 and 65535")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True)
    parser.add_argument("--remote-repo", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--guest-marker", default=DEFAULT_REMOTE_GUEST_MARKER)
    parser.add_argument("--guest-token-file", default=DEFAULT_REMOTE_TOKEN_FILE)
    parser.add_argument("--local-host", default=DEFAULT_LOCAL_HOST)
    parser.add_argument("--local-port", type=int, default=DEFAULT_LOCAL_PORT)
    parser.add_argument("--guest-port", type=int, default=DEFAULT_GUEST_PORT)
    parser.add_argument("--provider-id", default=DEFAULT_PROVIDER_ID)
    parser.add_argument("--remote-python", default=DEFAULT_REMOTE_PYTHON)
    parser.add_argument(
        "--remote-provider-script",
        default=DEFAULT_REMOTE_PROVIDER_SCRIPT,
    )
    parser.add_argument("--identity-file", default="")
    parser.add_argument("--ssh-option", action="append", default=[])
    parser.add_argument("--launch-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--manifest", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
