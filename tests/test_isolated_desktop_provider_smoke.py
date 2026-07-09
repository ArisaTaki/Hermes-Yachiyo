from __future__ import annotations

import json

from apps.shell.yachiyo_agent.desktop_provider_contract import (
    virtual_desktop_provider_manifest_template,
)
from scripts import smoke_isolated_desktop_provider as smoke


def test_isolated_desktop_provider_smoke_covers_operate_verify_sequence() -> None:
    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert evidence["desktop_session_kind"] == "isolated_desktop"
    assert evidence["desktop_session_isolated"] is True
    assert evidence["foreground_takeover_required"] is False
    assert evidence["checks"]["all_tools_routed"] is True
    assert evidence["checks"]["tool_sequence_completed"] is True
    assert evidence["checks"]["read_ui_returned_elements"] is True
    assert evidence["checks"]["verify_expected_text"] is True
    assert evidence["covered_tools"] == list(smoke.SMOKE_TOOLS)
    assert evidence["provider_conformance"]["ok"] is True
    assert evidence["provider_conformance"]["smoke_ok"] is True
    assert evidence["provider_conformance"]["public_release_ready"] is False
    assert evidence["provider_conformance"]["release_candidate"] is False
    assert "loopback_desktop_backend" in evidence["provider_conformance"][
        "release_blocking_conditions"
    ]
    assert [item["action"] for item in evidence["tool_results"]] == list(
        smoke.SMOKE_TOOLS
    )


def test_isolated_desktop_provider_smoke_can_use_configured_provider(monkeypatch) -> None:
    class FakeRegistry:
        def execute_if_routed(
            self,
            tool_name,
            payload,
            *,
            tool_request,
            broker,
            approved=False,
        ):
            return {
                "ok": True,
                "tool": tool_name,
                "action": tool_name,
                "desktop_execution_provider_routed": True,
                "sandbox_provider": dict(tool_request.get("sandbox_provider") or {}),
                "data": {"verification_passed": tool_name == "desktop.verify"},
            }

    monkeypatch.setattr(
        smoke,
        "desktop_execution_provider_status_from_env",
        lambda *args, **kwargs: {
            "configured": True,
            "available": True,
            "adapter_ready": True,
            "provider_id": "real-virtual-desktop",
            "endpoint_origin": "http://127.0.0.1:29093",
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "keyboard_mouse_capture_supported": True,
            "desktop_backend_kind": "virtual_desktop_backend",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": True,
            "requires_real_virtual_desktop_backend": False,
            "supported_tools": list(smoke.SMOKE_TOOLS),
        },
    )
    monkeypatch.setattr(
        smoke,
        "desktop_execution_provider_registry_from_env",
        lambda *args, **kwargs: FakeRegistry(),
    )

    evidence = smoke.run_smoke(use_configured_provider=True)

    assert evidence["ok"] is True
    assert evidence["use_configured_provider"] is True
    assert evidence["desktop_backend_kind"] == "virtual_desktop_backend"
    assert evidence["desktop_backend_is_loopback"] is False
    assert evidence["desktop_backend_ready_for_public_release"] is True
    assert evidence["requires_real_virtual_desktop_backend"] is False
    assert evidence["checks"]["provider_backend_ready_for_public_release"] is True
    assert evidence["checks"]["provider_backend_not_loopback"] is True
    assert evidence["checks"]["provider_contract_ready"] is True
    assert evidence["provider_contract"]["ok"] is True
    assert evidence["provider_conformance"]["ok"] is True
    assert evidence["provider_conformance"]["mode"] == (
        "release_virtual_desktop_provider_conformance"
    )
    assert evidence["provider_conformance"]["public_release_ready"] is True
    assert evidence["provider_conformance"]["release_candidate"] is True
    assert evidence["provider_conformance"]["blocking_conditions"] == []
    assert evidence["provider_conformance"]["release_blocking_conditions"] == []
    assert evidence["provider_conformance"]["covered_tools"] == list(smoke.SMOKE_TOOLS)
    assert evidence["checks"]["all_tool_results_isolated"] is True
    assert evidence["tool_results"][0]["sandbox_provider"][
        "desktop_session_isolated"
    ] is True
    assert [item["action"] for item in evidence["tool_results"]] == list(
        smoke.SMOKE_TOOLS
    )


def test_isolated_desktop_provider_smoke_rejects_remote_manifest_before_start(
    tmp_path,
    monkeypatch,
) -> None:
    manifest_path = tmp_path / "remote-provider-manifest.json"
    template = virtual_desktop_provider_manifest_template(
        provider_id="remote-provider",
        base_url="https://provider.example.com",
    )
    manifest_path.write_text(
        json.dumps(template, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        smoke,
        "desktop_execution_provider_status_from_env",
        lambda *args, **kwargs: {
            "configured": False,
            "available": False,
            "adapter_ready": False,
            "status": "not_configured",
        },
    )

    evidence = smoke.run_smoke(provider_manifest=manifest_path)

    assert evidence["ok"] is False
    assert evidence["reason"] == "provider_manifest_contract_failed"
    assert evidence["provider_manifest_evidence"]["ok"] is False
    assert "desktop_provider_manifest_remote_endpoint_not_allowed" in evidence[
        "provider_manifest_evidence"
    ]["blocking_conditions"]
    assert "desktop_provider_manifest_remote_endpoint_not_allowed" in evidence[
        "provider_contract"
    ]["blocking_conditions"]
    assert "desktop_provider_manifest_remote_endpoint_not_allowed" in evidence[
        "provider_conformance"
    ]["release_blocking_conditions"]
    assert evidence["provider_conformance"]["public_release_ready"] is False
    assert evidence["tool_results"] == []


def test_isolated_desktop_provider_smoke_can_start_managed_configured_provider(
    monkeypatch,
) -> None:
    state = {"started": False, "stopped": False}

    class FakeRegistry:
        def execute_if_routed(
            self,
            tool_name,
            payload,
            *,
            tool_request,
            broker,
            approved=False,
        ):
            return {
                "ok": True,
                "tool": tool_name,
                "action": tool_name,
                "desktop_execution_provider_routed": True,
                "sandbox_provider": dict(tool_request.get("sandbox_provider") or {}),
                "data": {"verification_passed": tool_name == "desktop.verify"},
            }

    def fake_status(*args, **kwargs):
        if not state["started"]:
            return {
                "configured": False,
                "available": False,
                "adapter_ready": False,
                "status": "not_configured",
            }
        return {
            "configured": True,
            "available": True,
            "adapter_ready": True,
            "provider_id": "managed-virtual-desktop",
            "endpoint_origin": "http://127.0.0.1:29093",
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "keyboard_mouse_capture_supported": True,
            "desktop_backend_kind": "virtual_desktop_backend",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": True,
            "requires_real_virtual_desktop_backend": False,
            "supported_tools": list(smoke.SMOKE_TOOLS),
        }

    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND",
        "python -m fake_virtual_desktop_provider",
    )
    monkeypatch.setattr(
        smoke,
        "desktop_execution_provider_status_from_env",
        fake_status,
    )
    monkeypatch.setattr(
        smoke,
        "desktop_execution_provider_registry_from_env",
        lambda *args, **kwargs: FakeRegistry(),
    )
    monkeypatch.setattr(
        smoke,
        "start_isolated_desktop_provider_session",
        lambda request=None: state.update(started=True)
        or {
            "ok": True,
            "started": True,
            "running": True,
            "provider_id": "managed-virtual-desktop",
        },
    )
    monkeypatch.setattr(
        smoke,
        "stop_isolated_desktop_provider_session",
        lambda: state.update(stopped=True) or {"ok": True, "stopped": True},
    )

    evidence = smoke.run_smoke(use_configured_provider=True)

    assert evidence["ok"] is True
    assert evidence["use_configured_provider"] is True
    assert evidence["managed_provider_started"] is True
    assert evidence["managed_provider_session"]["provider_id"] == "managed-virtual-desktop"
    assert state["stopped"] is True
    assert evidence["desktop_backend_ready_for_public_release"] is True
    assert evidence["provider_contract"]["ok"] is True
    assert evidence["provider_conformance"]["public_release_ready"] is True


def test_isolated_desktop_provider_smoke_reports_managed_start_failure(
    monkeypatch,
) -> None:
    provider_contract = {
        "ok": False,
        "blocking_conditions": [
            "managed_external_provider_start_failed",
            "provider_unavailable",
        ],
        "missing_required_tools": [],
        "required_tools": list(smoke.SMOKE_TOOLS),
        "supported_tools": list(smoke.SMOKE_TOOLS),
    }
    provider_conformance = {
        "ok": False,
        "mode": "managed_external_provider_start_check",
        "runtime_checked": False,
        "release_candidate": False,
        "public_release_ready": False,
        "smoke_ok": None,
        "provider_contract_ok": False,
        "required_tools": list(smoke.SMOKE_TOOLS),
        "covered_tools": list(smoke.SMOKE_TOOLS),
        "missing_required_tools": [],
        "failed_tools": [],
        "blocking_conditions": [
            "managed_external_provider_start_failed",
            "provider_unavailable",
        ],
        "release_blocking_conditions": [
            "managed_external_provider_start_failed",
            "provider_unavailable",
        ],
        "provider_contract_blocking_conditions": [
            "managed_external_provider_start_failed",
            "provider_unavailable",
        ],
    }

    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND",
        "python -m fake_virtual_desktop_provider",
    )
    monkeypatch.setattr(
        smoke,
        "desktop_execution_provider_status_from_env",
        lambda *args, **kwargs: {
            "configured": False,
            "available": False,
            "adapter_ready": False,
            "status": "not_configured",
        },
    )
    monkeypatch.setattr(
        smoke,
        "start_isolated_desktop_provider_session",
        lambda request=None: {
            "ok": False,
            "status": "start_failed",
            "running": False,
            "started": False,
            "reason": "managed_external_provider_start_failed",
            "error": "managed desktop provider launch failed",
            "provider_id": "managed-external-desktop",
            "provider_contract": provider_contract,
            "provider_conformance": provider_conformance,
        },
    )

    evidence = smoke.run_smoke(use_configured_provider=True)

    assert evidence["ok"] is False
    assert evidence["reason"] == "managed_external_provider_start_failed"
    assert evidence["managed_provider_started"] is False
    assert evidence["managed_provider_session"]["status"] == "start_failed"
    assert evidence["provider_contract"] == provider_contract
    assert evidence["provider_conformance"] == provider_conformance
