from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from apps.shell.agent.runtime import virtual_desktop_guest_provider as guest
from apps.shell.yachiyo_agent.desktop_provider_contract import (
    OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    virtual_desktop_provider_contract_evidence,
    virtual_desktop_provider_manifest_contract_evidence,
)


def _write_guest_marker(path: Path, *, session_id: str = "guest-session-1") -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": guest.VIRTUAL_DESKTOP_GUEST_MARKER_SCHEMA,
                "session_id": session_id,
                "boot_session_id": "boot-session-1",
                "hardware_model": "VirtualMac2,1",
                "desktop_backend_kind": "test_macos_virtual_machine",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _attested_provider(monkeypatch, tmp_path: Path) -> guest.VirtualDesktopGuestProvider:
    marker = tmp_path / "guest.json"
    _write_guest_marker(marker)
    monkeypatch.setattr(guest.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guest, "_macos_boot_session_id", lambda: "boot-session-1")
    monkeypatch.setattr(guest, "_macos_hardware_model", lambda: "VirtualMac2,1")
    return guest.VirtualDesktopGuestProvider(
        session_id="guest-session-1",
        marker_path=marker,
    )


def test_virtual_desktop_guest_attestation_rejects_missing_marker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(guest.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guest, "_macos_boot_session_id", lambda: "boot-session-1")
    monkeypatch.setattr(guest, "_macos_hardware_model", lambda: "VirtualMac2,1")

    evidence = guest.virtual_desktop_guest_attestation(
        marker_path=tmp_path / "missing.json",
        session_id="guest-session-1",
    )

    assert evidence["ok"] is False
    assert "virtual_desktop_guest_marker_missing" in evidence["blocking_conditions"]


def test_virtual_desktop_guest_status_and_manifest_are_release_contract_ready(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider = _attested_provider(monkeypatch, tmp_path)

    status = provider.status()
    manifest = provider.manifest(base_url="http://127.0.0.1:39097")
    contract = virtual_desktop_provider_contract_evidence(
        {
            **status,
            "configured": True,
            "available": True,
            "adapter_ready": True,
            "authentication_configured": True,
        },
        required_tools=OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    )
    manifest_contract = virtual_desktop_provider_manifest_contract_evidence(manifest)

    assert status["ok"] is True
    assert status["desktop_session_kind"] == "virtual_desktop"
    assert status["desktop_session_isolated"] is True
    assert status["foreground_takeover_required"] is False
    assert status["desktop_backend_is_loopback"] is False
    assert status["desktop_backend_ready_for_public_release"] is True
    assert status["requires_real_virtual_desktop_backend"] is False
    assert "idempotent_tool_requests" in status["capabilities"]
    assert contract["ok"] is True
    assert manifest_contract["ok"] is True


def test_virtual_desktop_guest_manifest_command_does_not_require_session_id(
    capsys,
) -> None:
    exit_code = guest.main(["--manifest"])
    manifest = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert virtual_desktop_provider_manifest_contract_evidence(manifest)["ok"] is True

    with pytest.raises(SystemExit) as exc_info:
        guest.main([])
    assert exc_info.value.code == 2


def test_virtual_desktop_guest_refuses_tools_without_attestation(tmp_path: Path) -> None:
    provider = guest.VirtualDesktopGuestProvider(
        session_id="guest-session-1",
        marker_path=tmp_path / "missing.json",
    )

    result = provider.execute("app.open", {"app_name": "Music"}, approved=True)

    assert result["ok"] is False
    assert result["error"] == "virtual_desktop_guest_attestation_failed"


def test_virtual_desktop_guest_executes_generic_controlled_tool(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider = _attested_provider(monkeypatch, tmp_path)
    calls: list[str] = []

    def fake_open(app_name: str) -> dict[str, Any]:
        calls.append(app_name)
        return {"ok": True, "action": "app.open", "summary": f"opened {app_name}"}

    monkeypatch.setattr(
        "apps.shell.agent.runtime.controlled_desktop_provider.desktop.app_open",
        fake_open,
    )

    result = provider.execute("app.open", {"app_name": "PixelForge"})

    assert result["ok"] is True
    assert calls == ["PixelForge"]
    assert result["sandbox_provider"]["desktop_session_isolated"] is True
    assert result["sandbox_provider"]["desktop_backend_is_loopback"] is False


def test_virtual_desktop_guest_server_requires_token(monkeypatch, tmp_path: Path) -> None:
    provider = _attested_provider(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="requires a bearer token"):
        guest.build_virtual_desktop_guest_provider_server(
            host="127.0.0.1",
            port=0,
            token="",
            provider=provider,
        )


def test_virtual_desktop_guest_http_status_reports_authentication(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider = _attested_provider(monkeypatch, tmp_path)
    server = guest.build_virtual_desktop_guest_provider_server(
        host="127.0.0.1",
        port=0,
        token="secret",
        provider=provider,
        quiet=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/status",
            headers={"Authorization": "Bearer secret"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            status = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status["ok"] is True
    assert status["authentication_configured"] is True
    assert status["guest_attestation"]["ok"] is True


def test_virtual_desktop_guest_marker_command_rejects_non_macos(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setattr(guest.platform, "system", lambda: "Linux")
    monkeypatch.setattr(guest, "_macos_boot_session_id", lambda: "")
    monkeypatch.setattr(guest, "_macos_hardware_model", lambda: "")

    exit_code = guest.main(
        [
            "--session-id",
            "guest-session-1",
            "--write-guest-marker",
            str(tmp_path / "guest.json"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["ok"] is False
    assert "virtual_desktop_guest_requires_macos" in payload["blocking_conditions"]
    assert not (tmp_path / "guest.json").exists()


def test_virtual_desktop_guest_attestation_rejects_physical_mac(
    monkeypatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "guest.json"
    _write_guest_marker(marker)
    monkeypatch.setattr(guest.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guest, "_macos_boot_session_id", lambda: "boot-session-1")
    monkeypatch.setattr(guest, "_macos_hardware_model", lambda: "Mac15,7")

    evidence = guest.virtual_desktop_guest_attestation(
        marker_path=marker,
        session_id="guest-session-1",
    )

    assert evidence["ok"] is False
    assert "virtual_desktop_guest_hardware_not_virtual" in evidence[
        "blocking_conditions"
    ]


def test_virtual_desktop_guest_marker_command_writes_current_vm_identity(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    marker = tmp_path / "guest.json"
    monkeypatch.setattr(guest.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guest, "_macos_boot_session_id", lambda: "boot-session-1")
    monkeypatch.setattr(guest, "_macos_hardware_model", lambda: "VirtualMac2,1")

    exit_code = guest.main(
        [
            "--session-id",
            "guest-session-1",
            "--write-guest-marker",
            str(marker),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    payload = json.loads(marker.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert output == {"ok": True, "marker_path": str(marker)}
    assert payload["boot_session_id"] == "boot-session-1"
    assert payload["hardware_model"] == "VirtualMac2,1"
    assert marker.stat().st_mode & 0o077 == 0
