from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.shell.yachiyo_agent import isolated_provider_session as session
from apps.shell.agent.runtime import virtual_desktop_guest_provider as guest
from apps.shell.yachiyo_agent.desktop_provider_contract import (
    virtual_desktop_provider_manifest_contract_evidence,
)
from apps.shell.yachiyo_agent.virtual_desktop_ssh_bridge import (
    SshVirtualDesktopBridgeConfig,
    _ssh_subprocess_env,
    authenticated_ssh_bridge_status,
    ssh_bridge_launch_payload,
    ssh_virtual_desktop_command,
    ssh_virtual_desktop_provider_manifest,
)


def _config() -> SshVirtualDesktopBridgeConfig:
    return SshVirtualDesktopBridgeConfig(
        ssh_target="yachiyo@192.0.2.10",
        remote_repo="/Users/yachiyo/Hermes-Yachiyo",
        session_id="vm-session-1",
        guest_marker="~/Library/Application Support/Oha-Yachiyo/guest.json",
        guest_token_file="~/Library/Application Support/Oha-Yachiyo/provider.token",
        local_port=39097,
        guest_port=29097,
        identity_file="~/.ssh/oha-vm",
        ssh_options=("StrictHostKeyChecking=yes",),
    )


def _packaged_config() -> SshVirtualDesktopBridgeConfig:
    return SshVirtualDesktopBridgeConfig(
        ssh_target="yachiyo@192.0.2.10",
        remote_repo="",
        session_id="vm-session-1",
        remote_provider_executable="/usr/local/bin/oha-yachiyo-desktop-provider",
        host_bridge_executable=(
            "/Applications/Oha-Yachiyo.app/Contents/Resources/desktop-provider/"
            "oha-yachiyo-virtual-desktop-bridge"
        ),
        local_port=39097,
    )


def test_ssh_virtual_desktop_command_uses_tunnel_without_forwarding_token() -> None:
    command = ssh_virtual_desktop_command(_config())
    rendered = " ".join(command)

    assert command[0] == "ssh"
    assert "127.0.0.1:39097:127.0.0.1:29097" in command
    assert "run_virtual_desktop_guest_provider.py" in rendered
    assert "--token-file" in rendered
    assert "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN" not in rendered
    assert "StrictHostKeyChecking=yes" in command
    assert "ForwardAgent=no" in command


def test_ssh_virtual_desktop_command_runs_packaged_guest_without_python() -> None:
    command = ssh_virtual_desktop_command(_packaged_config())
    rendered = " ".join(command)

    assert "/usr/local/bin/oha-yachiyo-desktop-provider" in rendered
    assert "run_virtual_desktop_guest_provider.py" not in rendered
    assert "python3" not in rendered


def test_ssh_virtual_desktop_manifest_passes_static_contract() -> None:
    manifest = ssh_virtual_desktop_provider_manifest(_config())
    evidence = virtual_desktop_provider_manifest_contract_evidence(manifest)

    assert evidence["ok"] is True
    assert manifest["entrypoint"]["script"] == (
        "scripts/run_ssh_virtual_desktop_provider.py"
    )
    assert manifest["entrypoint"]["launch_timeout_seconds"] == 45
    assert manifest["ssh_bridge"]["credentials_forwarded"] is False
    assert manifest["endpoint_urls"]["execute"] == (
        "http://127.0.0.1:39097/tools/execute"
    )


def test_packaged_ssh_manifest_omits_source_repo_requirement() -> None:
    manifest = ssh_virtual_desktop_provider_manifest(_packaged_config())
    argv = manifest["entrypoint"]["argv"]

    assert argv[0].endswith("oha-yachiyo-virtual-desktop-bridge")
    assert "--remote-provider-executable" in argv
    assert "--remote-repo" not in argv
    assert "script" not in manifest["entrypoint"]
    assert manifest["ssh_bridge"]["remote_repo"] == ""


def test_ssh_virtual_desktop_manifest_is_startable_by_session_manager(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    manifest_path = tmp_path / "provider.manifest.json"
    manifest = ssh_virtual_desktop_provider_manifest(_config())

    command = session._managed_external_provider_start_command(
        repo_root,
        manifest=manifest,
        manifest_path=manifest_path,
    )
    timeout = session._managed_external_provider_launch_timeout(
        manifest,
        default=10,
    )

    assert command[1] == str(repo_root / "scripts/run_ssh_virtual_desktop_provider.py")
    assert "--ssh-target" in command
    assert "--remote-repo" in command
    assert timeout == 45


def test_ssh_bridge_rewrites_guest_launch_to_host_loopback() -> None:
    launch = ssh_bridge_launch_payload(
        _config(),
        {
            "ok": True,
            "provider_id": guest.DEFAULT_PROVIDER_ID,
            "provider_kind": "sandbox_desktop",
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "desktop_backend_kind": "macos_virtual_machine",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": True,
            "requires_real_virtual_desktop_backend": False,
            "supported_tools": ["desktop.list_apps"],
            "capabilities": ["idempotent_tool_requests"],
            "url": "http://127.0.0.1:29097",
        },
    )

    assert launch["url"] == "http://127.0.0.1:39097"
    assert launch["execute_url"] == "http://127.0.0.1:39097/tools/execute"
    assert launch["source"] == "ssh_virtual_desktop_bridge"
    assert launch["ssh_bridge"]["credentials_forwarded"] is False


def test_ssh_bridge_launch_satisfies_managed_external_release_contract(
    monkeypatch,
) -> None:
    config = _config()
    manifest = ssh_virtual_desktop_provider_manifest(config)
    provider = guest.VirtualDesktopGuestProvider(
        provider_id=config.provider_id,
        session_id=config.session_id,
    )
    monkeypatch.setattr(
        provider,
        "attestation",
        lambda: {
            "ok": True,
            "desktop_backend_kind": "macos_virtual_machine",
            "blocking_conditions": [],
        },
    )
    launch = ssh_bridge_launch_payload(config, provider.status())
    launch["authentication_configured"] = True

    blockers = session._managed_external_provider_release_launch_blockers(
        manifest,
        launch,
    )

    assert blockers == []


def test_managed_external_release_contract_does_not_backfill_runtime_evidence(
    monkeypatch,
) -> None:
    config = _config()
    manifest = ssh_virtual_desktop_provider_manifest(config)
    provider = guest.VirtualDesktopGuestProvider(
        provider_id=config.provider_id,
        session_id=config.session_id,
    )
    monkeypatch.setattr(
        provider,
        "attestation",
        lambda: {
            "ok": True,
            "desktop_backend_kind": "macos_virtual_machine",
            "blocking_conditions": [],
        },
    )
    launch = ssh_bridge_launch_payload(config, provider.status())
    launch["authentication_configured"] = True
    launch.pop("supported_tools")
    launch["capabilities"] = []

    blockers = session._managed_external_provider_release_launch_blockers(
        manifest,
        launch,
    )

    assert "desktop_provider_idempotency_required" in blockers
    assert "desktop_provider_missing_required_tools" in blockers


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"ssh_target": "-oProxyCommand=bad"}, "SSH target"),
        ({"remote_repo": "~/Hermes-Yachiyo"}, "must be absolute"),
        ({"local_host": "0.0.0.0"}, "loopback"),
        ({"local_port": 0}, "local port"),
    ],
)
def test_ssh_bridge_rejects_unsafe_config(changes, message: str) -> None:
    config = _config()
    values = {**config.__dict__, **changes}

    with pytest.raises(ValueError, match=message):
        ssh_virtual_desktop_command(SshVirtualDesktopBridgeConfig(**values))


def test_virtual_desktop_guest_reads_restricted_token_file(tmp_path: Path) -> None:
    token_file = tmp_path / "provider.token"
    token_file.write_text("secret-token\n", encoding="utf-8")
    token_file.chmod(0o600)

    token = guest._desktop_provider_token(
        direct_token="",
        token_file=token_file,
    )

    assert token == "secret-token"


def test_virtual_desktop_guest_rejects_world_readable_token_file(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "provider.token"
    token_file.write_text("secret-token\n", encoding="utf-8")
    token_file.chmod(0o644)

    with pytest.raises(ValueError, match="permissions must be 0600"):
        guest._desktop_provider_token(
            direct_token="",
            token_file=token_file,
        )


def test_ssh_bridge_env_keeps_local_agent_but_drops_provider_token(monkeypatch) -> None:
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/test-agent.sock")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN", "provider-secret")

    env = _ssh_subprocess_env()

    assert env["SSH_AUTH_SOCK"] == "/tmp/test-agent.sock"
    assert "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN" not in env


def test_ssh_bridge_verifies_host_and_guest_token_match() -> None:
    requests = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "ok": True,
                    "provider_id": guest.DEFAULT_PROVIDER_ID,
                    "authentication_configured": True,
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    status = authenticated_ssh_bridge_status(
        _config(),
        token="provider-secret",
        urlopen=fake_urlopen,
    )

    assert status["ok"] is True
    request, timeout = requests[0]
    assert request.full_url == "http://127.0.0.1:39097/status"
    assert request.get_header("Authorization") == "Bearer provider-secret"
    assert timeout == 5.0


def test_ssh_bridge_requires_host_provider_token() -> None:
    with pytest.raises(RuntimeError, match="token is not configured"):
        authenticated_ssh_bridge_status(_config(), token="")
