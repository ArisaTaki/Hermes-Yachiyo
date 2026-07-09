from apps.shell.yachiyo_agent.desktop_provider_contract import (
    OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    virtual_desktop_provider_conformance_summary,
    virtual_desktop_provider_contract_evidence,
    virtual_desktop_provider_manifest_contract_evidence,
    virtual_desktop_provider_manifest_template,
)


def _release_ready_status() -> dict[str, object]:
    return {
        "configured": True,
        "available": True,
        "adapter_ready": True,
        "desktop_session_kind": "virtual_desktop",
        "desktop_session_isolated": True,
        "foreground_takeover_required": False,
        "keyboard_mouse_capture_supported": True,
        "desktop_backend_kind": "virtual_desktop_backend",
        "desktop_backend_is_loopback": False,
        "desktop_backend_ready_for_public_release": True,
        "requires_real_virtual_desktop_backend": False,
        "supported_tools": list(OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS),
    }


def test_virtual_desktop_provider_contract_accepts_release_ready_provider() -> None:
    tool_results = [
        {
            "ok": True,
            "tool": tool,
            "action": tool,
            "desktop_execution_provider_routed": True,
            "sandbox_provider": {"desktop_session_isolated": True},
        }
        for tool in OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS
    ]

    evidence = virtual_desktop_provider_contract_evidence(
        _release_ready_status(),
        required_tools=OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
        tool_results=tool_results,
    )

    assert evidence["ok"] is True
    assert evidence["blocking_conditions"] == []
    assert evidence["missing_required_tools"] == []
    assert evidence["desktop_session_kind"] == "virtual_desktop"
    assert evidence["desktop_session_isolated"] is True
    assert evidence["foreground_takeover_required"] is False
    assert evidence["keyboard_mouse_capture_supported"] is True
    assert evidence["checks"]["tool_sequence_covers_required_tools"] is True


def test_virtual_desktop_provider_contract_rejects_loopback_backend() -> None:
    status = {
        **_release_ready_status(),
        "desktop_backend_kind": "loopback_session_harness",
        "desktop_backend_is_loopback": True,
        "desktop_backend_ready_for_public_release": False,
        "requires_real_virtual_desktop_backend": True,
    }

    evidence = virtual_desktop_provider_contract_evidence(
        status,
        required_tools=OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    )

    assert evidence["ok"] is False
    assert "loopback_desktop_backend" in evidence["blocking_conditions"]
    assert "desktop_backend_not_release_ready" in evidence["blocking_conditions"]
    assert "real_virtual_desktop_backend_required" in evidence["blocking_conditions"]


def test_virtual_desktop_provider_contract_requires_tool_coverage() -> None:
    required = ["desktop.list_apps", "desktop.verify"]
    evidence = virtual_desktop_provider_contract_evidence(
        {**_release_ready_status(), "supported_tools": ["desktop.list_apps"]},
        required_tools=required,
    )

    assert evidence["ok"] is False
    assert evidence["missing_required_tools"] == ["desktop.verify"]
    assert "desktop_provider_missing_required_tools" in evidence["blocking_conditions"]


def test_virtual_desktop_provider_conformance_summary_matches_public_shape() -> None:
    contract = virtual_desktop_provider_contract_evidence(
        _release_ready_status(),
        required_tools=OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    )

    conformance = virtual_desktop_provider_conformance_summary(
        contract,
        status=_release_ready_status(),
        mode="session_manager_provider_contract_check",
        runtime_checked=True,
    )

    assert conformance["ok"] is True
    assert conformance["mode"] == "session_manager_provider_contract_check"
    assert conformance["runtime_checked"] is True
    assert conformance["public_release_ready"] is True
    assert conformance["release_candidate"] is True
    assert conformance["provider_contract_ok"] is True
    assert conformance["required_tools"] == list(OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS)
    assert conformance["covered_tools"] == list(OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS)
    assert conformance["release_blocking_conditions"] == []
    assert conformance["desktop_session_kind"] == "virtual_desktop"
    assert conformance["desktop_backend_is_loopback"] is False


def test_virtual_desktop_provider_contract_checks_tool_results_when_present() -> None:
    evidence = virtual_desktop_provider_contract_evidence(
        _release_ready_status(),
        required_tools=["desktop.verify"],
        tool_results=[
            {
                "ok": True,
                "tool": "desktop.verify",
                "desktop_execution_provider_routed": True,
                "sandbox_provider": {"desktop_session_isolated": False},
            }
        ],
    )

    assert evidence["ok"] is False
    assert "desktop_provider_tool_result_not_isolated" in evidence[
        "blocking_conditions"
    ]


def test_virtual_desktop_provider_manifest_template_matches_release_contract() -> None:
    template = virtual_desktop_provider_manifest_template(
        provider_id="real-provider",
        base_url="http://127.0.0.1:39097",
    )

    assert template["provider_id"] == "real-provider"
    assert template["provider_kind"] == "sandbox_desktop"
    assert template["endpoint_urls"]["status"] == "http://127.0.0.1:39097/status"
    assert template["endpoint_urls"]["execute"] == (
        "http://127.0.0.1:39097/tools/execute"
    )
    assert template["supported_tools"] == list(OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS)
    assert template["desktop_session_kind"] == "virtual_desktop"
    assert template["desktop_session_isolated"] is True
    assert template["foreground_takeover_required"] is False
    assert template["desktop_backend_is_loopback"] is False
    assert template["desktop_backend_ready_for_public_release"] is True
    assert template["requires_real_virtual_desktop_backend"] is False

    evidence = virtual_desktop_provider_contract_evidence(
        {
            **template,
            "configured": True,
            "available": True,
            "adapter_ready": True,
        },
        required_tools=OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    )

    assert evidence["ok"] is True
    assert evidence["blocking_conditions"] == []

    manifest_evidence = virtual_desktop_provider_manifest_contract_evidence(template)

    assert manifest_evidence["ok"] is True
    assert manifest_evidence["runtime_checked"] is False
    assert manifest_evidence["provider_id"] == "real-provider"
    assert manifest_evidence["status_url"] == "http://127.0.0.1:39097/status"
    assert manifest_evidence["execute_url"] == (
        "http://127.0.0.1:39097/tools/execute"
    )
    assert manifest_evidence["remote_endpoint_allowed"] is False
    assert manifest_evidence["remote_endpoint_urls"] == []
    assert manifest_evidence["blocking_conditions"] == []
    assert manifest_evidence["provider_conformance"]["mode"] == (
        "manifest_contract_check"
    )
    assert manifest_evidence["provider_conformance"]["runtime_checked"] is False
    assert manifest_evidence["provider_conformance"]["public_release_ready"] is True
    assert manifest_evidence["provider_conformance"]["release_blocking_conditions"] == []


def test_virtual_desktop_provider_manifest_contract_reports_static_blockers() -> None:
    template = virtual_desktop_provider_manifest_template()
    bad_manifest = {
        **template,
        "contract_version": "old",
        "provider_id": "",
        "provider_kind": "local_desktop",
        "supported_tools": ["desktop.list_apps"],
        "desktop_backend_is_loopback": True,
        "desktop_backend_ready_for_public_release": False,
        "requires_real_virtual_desktop_backend": True,
    }

    evidence = virtual_desktop_provider_manifest_contract_evidence(bad_manifest)

    assert evidence["ok"] is False
    assert "desktop_provider_manifest_contract_version_mismatch" in evidence[
        "blocking_conditions"
    ]
    assert "desktop_provider_manifest_provider_id_missing" in evidence[
        "blocking_conditions"
    ]
    assert "desktop_provider_manifest_wrong_provider_kind" in evidence[
        "blocking_conditions"
    ]
    assert "desktop_provider_missing_required_tools" in evidence[
        "blocking_conditions"
    ]
    assert "loopback_desktop_backend" in evidence["blocking_conditions"]
    assert "desktop_backend_not_release_ready" in evidence["blocking_conditions"]
    assert "real_virtual_desktop_backend_required" in evidence["blocking_conditions"]
    assert "desktop.verify" in evidence["missing_required_tools"]
    assert evidence["provider_conformance"]["public_release_ready"] is False
    assert "desktop_provider_missing_required_tools" in evidence[
        "provider_conformance"
    ]["release_blocking_conditions"]


def test_virtual_desktop_provider_manifest_contract_rejects_remote_endpoint_by_default() -> None:
    template = virtual_desktop_provider_manifest_template(
        provider_id="remote-provider",
        base_url="https://provider.example.com",
    )

    evidence = virtual_desktop_provider_manifest_contract_evidence(template)

    assert evidence["ok"] is False
    assert evidence["remote_endpoint_allowed"] is False
    assert evidence["remote_endpoint_urls"] == [
        "https://provider.example.com",
        "https://provider.example.com/status",
        "https://provider.example.com/tools/execute",
        "https://provider.example.com/health",
        "https://provider.example.com/manifest",
    ]
    assert "desktop_provider_manifest_remote_endpoint_not_allowed" in evidence[
        "blocking_conditions"
    ]


def test_virtual_desktop_provider_manifest_contract_allows_explicit_remote_endpoint() -> None:
    template = {
        **virtual_desktop_provider_manifest_template(
            provider_id="remote-provider",
            base_url="https://provider.example.com",
        ),
        "allow_remote": True,
    }

    evidence = virtual_desktop_provider_manifest_contract_evidence(template)

    assert evidence["ok"] is True
    assert evidence["remote_endpoint_allowed"] is True
    assert evidence["remote_endpoint_urls"]
    assert "desktop_provider_manifest_remote_endpoint_not_allowed" not in evidence[
        "blocking_conditions"
    ]
