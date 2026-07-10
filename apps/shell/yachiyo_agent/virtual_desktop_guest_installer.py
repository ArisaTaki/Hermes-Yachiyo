"""Provision the packaged desktop provider into an existing macOS VM."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shlex
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from apps.shell.agent.runtime.desktop_provider_credentials import (
    desktop_provider_token_from_file,
)
from apps.shell.agent.runtime.virtual_desktop_guest_provider import (
    DEFAULT_BACKEND_KIND,
    DEFAULT_PROVIDER_ID,
)
from apps.shell.yachiyo_agent.virtual_desktop_ssh_bridge import (
    DEFAULT_GUEST_PORT,
    DEFAULT_LOCAL_HOST,
    DEFAULT_LOCAL_PORT,
    SshVirtualDesktopBridgeConfig,
    ssh_virtual_desktop_provider_manifest,
)
from packages.security import redact_api_error_text, scrubbed_subprocess_env

_ROOT = Path(__file__).resolve().parents[3]


def _desktop_component_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parents[1] / "desktop-provider" / name
    return _ROOT / "dist" / "desktop-provider" / name


DEFAULT_PROVIDER_BINARY = _desktop_component_path("oha-yachiyo-desktop-provider")
DEFAULT_HOST_BRIDGE_BINARY = _desktop_component_path(
    "oha-yachiyo-virtual-desktop-bridge"
)
DEFAULT_LOCAL_TOKEN_FILE = Path(
    "~/Library/Application Support/Oha-Yachiyo/desktop-provider.token"
).expanduser()
DEFAULT_MANIFEST_PATH = Path(
    "~/Library/Application Support/Oha-Yachiyo/virtual-desktop-provider.manifest.json"
).expanduser()
DEFAULT_REMOTE_PROVIDER_SUFFIX = (
    "Library/Application Support/Oha-Yachiyo/bin/oha-yachiyo-desktop-provider"
)
DEFAULT_REMOTE_MARKER_SUFFIX = (
    "Library/Application Support/Oha-Yachiyo/virtual-desktop-guest.json"
)
DEFAULT_REMOTE_TOKEN_SUFFIX = (
    "Library/Application Support/Oha-Yachiyo/desktop-provider.token"
)

CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]
_COMPONENT_BUILD_LOCK = threading.Lock()


@dataclass(frozen=True)
class VirtualDesktopGuestInstallConfig:
    ssh_target: str
    session_id: str
    provider_binary: Path = DEFAULT_PROVIDER_BINARY
    host_bridge_binary: Path = DEFAULT_HOST_BRIDGE_BINARY
    local_token_file: Path = DEFAULT_LOCAL_TOKEN_FILE
    manifest_path: Path = DEFAULT_MANIFEST_PATH
    remote_provider_executable: str = ""
    remote_guest_marker: str = ""
    remote_token_file: str = ""
    local_host: str = DEFAULT_LOCAL_HOST
    local_port: int = DEFAULT_LOCAL_PORT
    guest_port: int = DEFAULT_GUEST_PORT
    provider_id: str = DEFAULT_PROVIDER_ID
    identity_file: str = ""
    ssh_options: tuple[str, ...] = ()


def ensure_virtual_desktop_guest_components(
    config: VirtualDesktopGuestInstallConfig,
    *,
    runner: CommandRunner = subprocess.run,
    timeout_seconds: float = 900.0,
) -> dict[str, Any]:
    """Build the default source-checkout components after explicit approval."""

    with _COMPONENT_BUILD_LOCK:
        return _ensure_virtual_desktop_guest_components(
            config,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )


def _ensure_virtual_desktop_guest_components(
    config: VirtualDesktopGuestInstallConfig,
    *,
    runner: CommandRunner,
    timeout_seconds: float,
) -> dict[str, Any]:

    provider_binary = Path(config.provider_binary).expanduser().resolve()
    host_bridge_binary = Path(config.host_bridge_binary).expanduser().resolve()
    components = {
        "guest_provider": provider_binary,
        "host_bridge": host_bridge_binary,
    }
    missing_before = [
        name
        for name, path in components.items()
        if not path.is_file() or not os.access(path, os.X_OK)
    ]
    if not missing_before:
        return {
            "ok": True,
            "status": "ready",
            "built": False,
            "components": {name: str(path) for name, path in components.items()},
            "missing_before": [],
        }
    if getattr(sys, "frozen", False):
        raise FileNotFoundError(
            "packaged virtual desktop components are missing: "
            + ", ".join(missing_before)
        )
    if (
        provider_binary != DEFAULT_PROVIDER_BINARY.resolve()
        or host_bridge_binary != DEFAULT_HOST_BRIDGE_BINARY.resolve()
    ):
        raise FileNotFoundError(
            "custom virtual desktop components are missing: "
            + ", ".join(missing_before)
        )

    build_script = _ROOT / "scripts" / "build_virtual_desktop_guest.py"
    command = [sys.executable, str(build_script)]
    completed = runner(
        command,
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
        env=scrubbed_subprocess_env(),
    )
    if completed.returncode != 0:
        output = str(completed.stderr or completed.stdout or "")
        detail = redact_api_error_text(output[-4000:])
        message = "virtual desktop component build failed"
        raise RuntimeError(f"{message}: {detail}" if detail else message)

    missing_after = [
        name
        for name, path in components.items()
        if not path.is_file() or not os.access(path, os.X_OK)
    ]
    if missing_after:
        raise FileNotFoundError(
            "virtual desktop component build did not create: "
            + ", ".join(missing_after)
        )
    return {
        "ok": True,
        "status": "built",
        "built": True,
        "components": {name: str(path) for name, path in components.items()},
        "missing_before": missing_before,
    }


def install_virtual_desktop_guest(
    config: VirtualDesktopGuestInstallConfig,
    *,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    """Install, attest, and write a startable host-side provider manifest."""

    _validate_install_config(config)
    provider_binary = Path(config.provider_binary).expanduser().resolve()
    host_bridge_binary = Path(config.host_bridge_binary).expanduser().resolve()
    local_token_file = Path(config.local_token_file).expanduser().resolve()
    manifest_path = Path(config.manifest_path).expanduser().resolve()
    remote_home = _remote_home(config, runner=runner)
    remote_provider = _remote_path(
        config.remote_provider_executable,
        home=remote_home,
        default_suffix=DEFAULT_REMOTE_PROVIDER_SUFFIX,
    )
    remote_marker = _remote_path(
        config.remote_guest_marker,
        home=remote_home,
        default_suffix=DEFAULT_REMOTE_MARKER_SUFFIX,
    )
    remote_token = _remote_path(
        config.remote_token_file,
        home=remote_home,
        default_suffix=DEFAULT_REMOTE_TOKEN_SUFFIX,
    )

    token, token_created = _load_or_create_token(local_token_file)
    provider_bytes = provider_binary.read_bytes()
    provider_sha256 = hashlib.sha256(provider_bytes).hexdigest()
    _install_remote_bytes(
        config,
        destination=remote_provider,
        payload=provider_bytes,
        mode=0o700,
        runner=runner,
    )
    _verify_remote_sha256(
        config,
        path=remote_provider,
        expected=provider_sha256,
        runner=runner,
    )
    _install_remote_bytes(
        config,
        destination=remote_token,
        payload=(token + "\n").encode("utf-8"),
        mode=0o600,
        runner=runner,
    )
    marker_result = _run_remote_json(
        config,
        [
            remote_provider,
            "--session-id",
            config.session_id,
            "--backend-kind",
            DEFAULT_BACKEND_KIND,
            "--write-guest-marker",
            remote_marker,
        ],
        runner=runner,
    )
    if marker_result.get("ok") is not True:
        blockers = ",".join(marker_result.get("blocking_conditions") or [])
        raise RuntimeError(
            "virtual desktop guest attestation failed"
            + (f": {blockers}" if blockers else "")
        )

    bridge_config = SshVirtualDesktopBridgeConfig(
        ssh_target=config.ssh_target,
        remote_repo="",
        session_id=config.session_id,
        guest_marker=remote_marker,
        guest_token_file=remote_token,
        local_host=config.local_host,
        local_port=config.local_port,
        guest_port=config.guest_port,
        provider_id=config.provider_id,
        remote_provider_executable=remote_provider,
        host_bridge_executable=str(host_bridge_binary),
        identity_file=config.identity_file,
        ssh_options=config.ssh_options,
    )
    manifest = ssh_virtual_desktop_provider_manifest(bridge_config)
    authentication = dict(manifest.get("authentication") or {})
    authentication["token_file"] = str(local_token_file)
    manifest["authentication"] = authentication
    manifest["installation"] = {
        "mode": "ssh_virtual_desktop_guest",
        "provider_sha256": provider_sha256,
        "remote_provider_executable": remote_provider,
        "remote_guest_marker": remote_marker,
        "remote_token_file": remote_token,
    }
    _write_json_file(manifest_path, manifest, mode=0o600)
    return {
        "ok": True,
        "ssh_target": config.ssh_target,
        "session_id": config.session_id,
        "provider_id": config.provider_id,
        "provider_sha256": provider_sha256,
        "remote_provider_executable": remote_provider,
        "remote_guest_marker": remote_marker,
        "remote_token_file": remote_token,
        "local_token_file": str(local_token_file),
        "local_token_created": token_created,
        "provider_manifest": str(manifest_path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--provider-binary", default=str(DEFAULT_PROVIDER_BINARY))
    parser.add_argument(
        "--host-bridge-binary",
        default=str(DEFAULT_HOST_BRIDGE_BINARY),
    )
    parser.add_argument("--local-token-file", default=str(DEFAULT_LOCAL_TOKEN_FILE))
    parser.add_argument("--manifest-out", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--remote-provider-executable", default="")
    parser.add_argument("--remote-guest-marker", default="")
    parser.add_argument("--remote-token-file", default="")
    parser.add_argument("--local-host", default=DEFAULT_LOCAL_HOST)
    parser.add_argument("--local-port", type=int, default=DEFAULT_LOCAL_PORT)
    parser.add_argument("--guest-port", type=int, default=DEFAULT_GUEST_PORT)
    parser.add_argument("--provider-id", default=DEFAULT_PROVIDER_ID)
    parser.add_argument("--identity-file", default="")
    parser.add_argument("--ssh-option", action="append", default=[])
    args = parser.parse_args(argv)
    config = VirtualDesktopGuestInstallConfig(
        ssh_target=args.ssh_target,
        session_id=args.session_id,
        provider_binary=Path(args.provider_binary),
        host_bridge_binary=Path(args.host_bridge_binary),
        local_token_file=Path(args.local_token_file),
        manifest_path=Path(args.manifest_out),
        remote_provider_executable=args.remote_provider_executable,
        remote_guest_marker=args.remote_guest_marker,
        remote_token_file=args.remote_token_file,
        local_host=args.local_host,
        local_port=args.local_port,
        guest_port=args.guest_port,
        provider_id=args.provider_id,
        identity_file=args.identity_file,
        ssh_options=tuple(args.ssh_option),
    )
    try:
        result = install_virtual_desktop_guest(config)
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": redact_api_error_text(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _remote_home(
    config: VirtualDesktopGuestInstallConfig,
    *,
    runner: CommandRunner,
) -> str:
    completed = _run_ssh(
        config,
        'test -n "$HOME" && printf "%s\\n" "$HOME"',
        runner=runner,
    )
    home = _stdout_text(completed).strip()
    if not home.startswith("/") or "\n" in home or "\r" in home:
        raise RuntimeError("virtual desktop guest returned an invalid home directory")
    return home.rstrip("/")


def _remote_path(value: str, *, home: str, default_suffix: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        clean = str(PurePosixPath(home) / default_suffix)
    elif clean == "~":
        clean = home
    elif clean.startswith("~/"):
        clean = str(PurePosixPath(home) / clean[2:])
    if not clean.startswith("/"):
        raise ValueError("remote desktop provider paths must be absolute or home-relative")
    if any(character in clean for character in ("\x00", "\n", "\r")):
        raise ValueError("remote desktop provider path contains invalid characters")
    return str(PurePosixPath(clean))


def _load_or_create_token(path: Path) -> tuple[str, bool]:
    if path.exists() or path.is_symlink():
        return desktop_provider_token_from_file(path), False
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(48)
    _write_text_file(path, token + "\n", mode=0o600)
    return token, True


def _install_remote_bytes(
    config: VirtualDesktopGuestInstallConfig,
    *,
    destination: str,
    payload: bytes,
    mode: int,
    runner: CommandRunner,
) -> None:
    quoted_destination = shlex.quote(destination)
    script = (
        "set -eu; "
        f"destination={quoted_destination}; "
        'parent=$(/usr/bin/dirname "$destination"); '
        '/bin/mkdir -p "$parent"; '
        'temporary="${destination}.tmp.$$"; '
        'trap \'/bin/rm -f "$temporary"\' EXIT HUP INT TERM; '
        '/bin/cat > "$temporary"; '
        f'/bin/chmod {mode:o} "$temporary"; '
        '/bin/mv -f "$temporary" "$destination"; '
        "trap - EXIT HUP INT TERM"
    )
    _run_ssh(config, script, input_bytes=payload, runner=runner)


def _verify_remote_sha256(
    config: VirtualDesktopGuestInstallConfig,
    *,
    path: str,
    expected: str,
    runner: CommandRunner,
) -> None:
    completed = _run_ssh(
        config,
        f"/usr/bin/shasum -a 256 -- {shlex.quote(path)}",
        runner=runner,
    )
    actual = _stdout_text(completed).strip().split(maxsplit=1)[0]
    if actual != expected:
        raise RuntimeError("virtual desktop guest provider checksum mismatch")


def _run_remote_json(
    config: VirtualDesktopGuestInstallConfig,
    argv: Sequence[str],
    *,
    runner: CommandRunner,
) -> dict[str, Any]:
    command = " ".join(shlex.quote(str(value)) for value in argv)
    completed = _run_ssh(config, command, runner=runner)
    try:
        payload = json.loads(_stdout_text(completed))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("virtual desktop guest returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("virtual desktop guest response must be an object")
    return payload


def _run_ssh(
    config: VirtualDesktopGuestInstallConfig,
    remote_command: str,
    *,
    runner: CommandRunner,
    input_bytes: bytes = b"",
) -> subprocess.CompletedProcess[Any]:
    command = _ssh_command(config, remote_command)
    completed = runner(
        command,
        input=input_bytes,
        capture_output=True,
        check=False,
        env=_ssh_subprocess_env(),
    )
    if completed.returncode != 0:
        detail = redact_api_error_text(_stderr_text(completed))
        message = "virtual desktop guest SSH command failed"
        raise RuntimeError(f"{message}: {detail}" if detail else message)
    return completed


def _ssh_command(
    config: VirtualDesktopGuestInstallConfig,
    remote_command: str,
) -> list[str]:
    command = ["ssh", "-T", "-o", "ForwardAgent=no"]
    if config.identity_file:
        command.extend(["-i", str(Path(config.identity_file).expanduser())])
    for option in config.ssh_options:
        command.extend(["-o", str(option)])
    command.extend([config.ssh_target, remote_command])
    return command


def _ssh_subprocess_env() -> dict[str, str]:
    env = scrubbed_subprocess_env()
    ssh_auth_sock = str(os.environ.get("SSH_AUTH_SOCK") or "").strip()
    if ssh_auth_sock:
        env["SSH_AUTH_SOCK"] = ssh_auth_sock
    return env


def _validate_install_config(config: VirtualDesktopGuestInstallConfig) -> None:
    if not config.ssh_target or config.ssh_target.startswith("-"):
        raise ValueError("SSH target is required and must not start with '-'")
    if not config.session_id:
        raise ValueError("virtual desktop session id is required")
    provider_binary = Path(config.provider_binary).expanduser()
    if not provider_binary.is_file():
        raise FileNotFoundError(f"desktop provider binary not found: {provider_binary}")
    if not os.access(provider_binary, os.X_OK):
        raise PermissionError("desktop provider binary is not executable")
    host_bridge_binary = Path(config.host_bridge_binary).expanduser()
    if not host_bridge_binary.is_file():
        raise FileNotFoundError(
            f"virtual desktop host bridge not found: {host_bridge_binary}"
        )
    if not os.access(host_bridge_binary, os.X_OK):
        raise PermissionError("virtual desktop host bridge is not executable")
    if config.local_host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("SSH bridge local host must be loopback")
    for label, value in (
        ("local port", config.local_port),
        ("guest port", config.guest_port),
    ):
        if not 1 <= int(value) <= 65535:
            raise ValueError(f"{label} must be between 1 and 65535")


def _write_text_file(path: Path, value: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(mode)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_file(path: Path, payload: dict[str, Any], *, mode: int) -> None:
    _write_text_file(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        mode=mode,
    )


def _stdout_text(completed: subprocess.CompletedProcess[Any]) -> str:
    value = completed.stdout or b""
    return (
        value.decode("utf-8", errors="replace")
        if isinstance(value, bytes)
        else str(value)
    )


def _stderr_text(completed: subprocess.CompletedProcess[Any]) -> str:
    value = completed.stderr or b""
    return (
        value.decode("utf-8", errors="replace")
        if isinstance(value, bytes)
        else str(value)
    )


if __name__ == "__main__":
    raise SystemExit(main())
