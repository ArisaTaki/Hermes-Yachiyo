from __future__ import annotations

import hashlib
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from apps.shell.yachiyo_agent import virtual_desktop_guest_installer as installer
from apps.shell.agent.runtime.desktop_provider_credentials import (
    desktop_provider_token_from_manifest,
)
from apps.shell.yachiyo_agent.virtual_desktop_guest_installer import (
    VirtualDesktopGuestInstallConfig,
    ensure_virtual_desktop_guest_components,
    install_virtual_desktop_guest,
)


class FakeSshRunner:
    def __init__(self, *, provider_sha256: str) -> None:
        self.provider_sha256 = provider_sha256
        self.calls: list[dict[str, Any]] = []

    def __call__(self, command, **kwargs):
        remote_command = command[-1]
        payload = kwargs.get("input", b"")
        self.calls.append(
            {
                "command": list(command),
                "remote_command": remote_command,
                "input": payload,
                "env": kwargs.get("env", {}),
            }
        )
        if 'printf "%s\\n" "$HOME"' in remote_command:
            stdout = b"/Users/yachiyo\n"
        elif "/usr/bin/shasum" in remote_command:
            stdout = f"{self.provider_sha256}  provider\n".encode()
        elif "--write-guest-marker" in remote_command:
            stdout = json.dumps({"ok": True, "marker_path": "/guest.json"}).encode()
        else:
            stdout = b""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")


def _config(tmp_path: Path, provider_binary: Path) -> VirtualDesktopGuestInstallConfig:
    host_bridge = tmp_path / "oha-yachiyo-virtual-desktop-bridge"
    host_bridge.write_bytes(b"host-bridge")
    host_bridge.chmod(0o700)
    return VirtualDesktopGuestInstallConfig(
        ssh_target="yachiyo@192.0.2.10",
        session_id="vm-session-1",
        provider_binary=provider_binary,
        host_bridge_binary=host_bridge,
        local_token_file=tmp_path / "provider.token",
        manifest_path=tmp_path / "provider.manifest.json",
        identity_file="~/.ssh/oha-vm",
        ssh_options=("StrictHostKeyChecking=yes",),
    )


def test_component_preflight_skips_build_when_binaries_are_ready(tmp_path) -> None:
    provider_binary = tmp_path / "provider"
    provider_binary.write_bytes(b"provider")
    provider_binary.chmod(0o700)
    config = _config(tmp_path, provider_binary)

    result = ensure_virtual_desktop_guest_components(
        config,
        runner=lambda *_args, **_kwargs: pytest.fail("build must not run"),
    )

    assert result["status"] == "ready"
    assert result["built"] is False
    assert result["missing_before"] == []


def test_component_preflight_builds_missing_default_source_components(
    monkeypatch,
    tmp_path,
) -> None:
    provider_binary = tmp_path / "dist" / "oha-yachiyo-desktop-provider"
    host_bridge = tmp_path / "dist" / "oha-yachiyo-virtual-desktop-bridge"
    monkeypatch.setattr(installer, "DEFAULT_PROVIDER_BINARY", provider_binary)
    monkeypatch.setattr(installer, "DEFAULT_HOST_BRIDGE_BINARY", host_bridge)
    monkeypatch.setattr(installer, "_ROOT", tmp_path)
    monkeypatch.delattr(installer.sys, "frozen", raising=False)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_build(command, **kwargs):
        calls.append((list(command), dict(kwargs)))
        provider_binary.parent.mkdir(parents=True, exist_ok=True)
        provider_binary.write_bytes(b"provider")
        provider_binary.chmod(0o700)
        host_bridge.write_bytes(b"bridge")
        host_bridge.chmod(0o700)
        return subprocess.CompletedProcess(command, 0, stdout="built", stderr="")

    config = VirtualDesktopGuestInstallConfig(
        ssh_target="yachiyo@192.0.2.10",
        session_id="vm-session-1",
        provider_binary=provider_binary,
        host_bridge_binary=host_bridge,
    )

    result = ensure_virtual_desktop_guest_components(config, runner=fake_build)

    assert result["status"] == "built"
    assert result["built"] is True
    assert result["missing_before"] == ["guest_provider", "host_bridge"]
    command, kwargs = calls[0]
    assert command == [
        installer.sys.executable,
        str(tmp_path / "scripts/build_virtual_desktop_guest.py"),
    ]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["check"] is False
    assert kwargs["timeout"] == 900.0
    assert "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN" not in kwargs["env"]


def test_component_preflight_does_not_build_missing_custom_components(
    tmp_path,
) -> None:
    config = VirtualDesktopGuestInstallConfig(
        ssh_target="yachiyo@192.0.2.10",
        session_id="vm-session-1",
        provider_binary=tmp_path / "custom-provider",
        host_bridge_binary=tmp_path / "custom-bridge",
    )

    with pytest.raises(FileNotFoundError, match="custom virtual desktop components"):
        ensure_virtual_desktop_guest_components(
            config,
            runner=lambda *_args, **_kwargs: pytest.fail("build must not run"),
        )


def test_component_preflight_rejects_missing_frozen_components(
    monkeypatch,
    tmp_path,
) -> None:
    provider_binary = tmp_path / "provider"
    host_bridge = tmp_path / "bridge"
    monkeypatch.setattr(installer, "DEFAULT_PROVIDER_BINARY", provider_binary)
    monkeypatch.setattr(installer, "DEFAULT_HOST_BRIDGE_BINARY", host_bridge)
    monkeypatch.setattr(installer.sys, "frozen", True, raising=False)
    config = VirtualDesktopGuestInstallConfig(
        ssh_target="yachiyo@192.0.2.10",
        session_id="vm-session-1",
        provider_binary=provider_binary,
        host_bridge_binary=host_bridge,
    )

    with pytest.raises(FileNotFoundError, match="packaged virtual desktop components"):
        ensure_virtual_desktop_guest_components(
            config,
            runner=lambda *_args, **_kwargs: pytest.fail("build must not run"),
        )


def test_component_preflight_reports_build_failure(monkeypatch, tmp_path) -> None:
    provider_binary = tmp_path / "provider"
    host_bridge = tmp_path / "bridge"
    monkeypatch.setattr(installer, "DEFAULT_PROVIDER_BINARY", provider_binary)
    monkeypatch.setattr(installer, "DEFAULT_HOST_BRIDGE_BINARY", host_bridge)
    monkeypatch.setattr(installer, "_ROOT", tmp_path)
    monkeypatch.delattr(installer.sys, "frozen", raising=False)
    config = VirtualDesktopGuestInstallConfig(
        ssh_target="yachiyo@192.0.2.10",
        session_id="vm-session-1",
        provider_binary=provider_binary,
        host_bridge_binary=host_bridge,
    )

    with pytest.raises(RuntimeError, match="component build failed"):
        ensure_virtual_desktop_guest_components(
            config,
            runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="PyInstaller failed",
            ),
        )


def test_component_preflight_requires_both_build_outputs(monkeypatch, tmp_path) -> None:
    provider_binary = tmp_path / "provider"
    host_bridge = tmp_path / "bridge"
    monkeypatch.setattr(installer, "DEFAULT_PROVIDER_BINARY", provider_binary)
    monkeypatch.setattr(installer, "DEFAULT_HOST_BRIDGE_BINARY", host_bridge)
    monkeypatch.setattr(installer, "_ROOT", tmp_path)
    monkeypatch.delattr(installer.sys, "frozen", raising=False)
    config = VirtualDesktopGuestInstallConfig(
        ssh_target="yachiyo@192.0.2.10",
        session_id="vm-session-1",
        provider_binary=provider_binary,
        host_bridge_binary=host_bridge,
    )

    with pytest.raises(FileNotFoundError, match="guest_provider, host_bridge"):
        ensure_virtual_desktop_guest_components(
            config,
            runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command,
                0,
                stdout="built",
                stderr="",
            ),
        )


def test_component_preflight_serializes_concurrent_builds(monkeypatch, tmp_path) -> None:
    provider_binary = tmp_path / "provider"
    host_bridge = tmp_path / "bridge"
    monkeypatch.setattr(installer, "DEFAULT_PROVIDER_BINARY", provider_binary)
    monkeypatch.setattr(installer, "DEFAULT_HOST_BRIDGE_BINARY", host_bridge)
    monkeypatch.setattr(installer, "_ROOT", tmp_path)
    monkeypatch.delattr(installer.sys, "frozen", raising=False)
    calls: list[list[str]] = []

    def fake_build(command, **_kwargs):
        calls.append(list(command))
        time.sleep(0.05)
        provider_binary.write_bytes(b"provider")
        provider_binary.chmod(0o700)
        host_bridge.write_bytes(b"bridge")
        host_bridge.chmod(0o700)
        return subprocess.CompletedProcess(command, 0, stdout="built", stderr="")

    config = VirtualDesktopGuestInstallConfig(
        ssh_target="yachiyo@192.0.2.10",
        session_id="vm-session-1",
        provider_binary=provider_binary,
        host_bridge_binary=host_bridge,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: ensure_virtual_desktop_guest_components(
                    config,
                    runner=fake_build,
                ),
                range(2),
            )
        )

    assert len(calls) == 1
    assert sorted(result["status"] for result in results) == ["built", "ready"]


def test_installer_streams_binary_and_token_then_writes_startable_manifest(
    tmp_path,
) -> None:
    provider_binary = tmp_path / "oha-yachiyo-desktop-provider"
    provider_binary.write_bytes(b"packaged-provider")
    provider_binary.chmod(0o700)
    digest = hashlib.sha256(provider_binary.read_bytes()).hexdigest()
    runner = FakeSshRunner(provider_sha256=digest)
    config = _config(tmp_path, provider_binary)

    result = install_virtual_desktop_guest(config, runner=runner)

    assert result["ok"] is True
    assert result["provider_sha256"] == digest
    assert result["remote_provider_executable"] == (
        "/Users/yachiyo/Library/Application Support/Oha-Yachiyo/bin/"
        "oha-yachiyo-desktop-provider"
    )
    token_file = tmp_path / "provider.token"
    assert token_file.stat().st_mode & 0o077 == 0
    manifest = json.loads((tmp_path / "provider.manifest.json").read_text())
    assert manifest["entrypoint"]["argv"][0].endswith(
        "oha-yachiyo-virtual-desktop-bridge"
    )
    assert "--remote-provider-executable" in manifest["entrypoint"]["argv"]
    assert manifest["authentication"]["token_file"] == str(token_file)
    assert desktop_provider_token_from_manifest(manifest)
    transferred = [call["input"] for call in runner.calls if call["input"]]
    assert provider_binary.read_bytes() in transferred
    assert (
        desktop_provider_token_from_manifest(manifest) + "\n"
    ).encode() in transferred


def test_installer_never_puts_token_in_ssh_command_or_manifest(tmp_path) -> None:
    provider_binary = tmp_path / "provider"
    provider_binary.write_bytes(b"provider")
    provider_binary.chmod(0o700)
    token_file = tmp_path / "provider.token"
    token_file.write_text("do-not-leak-this-token\n", encoding="utf-8")
    token_file.chmod(0o600)
    digest = hashlib.sha256(provider_binary.read_bytes()).hexdigest()
    runner = FakeSshRunner(provider_sha256=digest)
    config = _config(tmp_path, provider_binary)

    install_virtual_desktop_guest(config, runner=runner)

    rendered_commands = json.dumps([call["command"] for call in runner.calls])
    manifest_text = (tmp_path / "provider.manifest.json").read_text()
    assert "do-not-leak-this-token" not in rendered_commands
    assert "do-not-leak-this-token" not in manifest_text
    assert all(
        call["env"].get("OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN") is None
        for call in runner.calls
    )


def test_installer_rejects_remote_checksum_mismatch(tmp_path) -> None:
    provider_binary = tmp_path / "provider"
    provider_binary.write_bytes(b"provider")
    provider_binary.chmod(0o700)
    runner = FakeSshRunner(provider_sha256="0" * 64)

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        install_virtual_desktop_guest(
            _config(tmp_path, provider_binary),
            runner=runner,
        )


def test_installer_rejects_non_executable_provider_binary(tmp_path) -> None:
    provider_binary = tmp_path / "provider"
    provider_binary.write_bytes(b"provider")
    provider_binary.chmod(0o600)

    with pytest.raises(PermissionError, match="not executable"):
        install_virtual_desktop_guest(
            _config(tmp_path, provider_binary),
            runner=FakeSshRunner(provider_sha256=""),
        )
