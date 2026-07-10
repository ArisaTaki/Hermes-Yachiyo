"""Shared contract checks for external desktop execution providers."""

from __future__ import annotations

import ipaddress
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

DESKTOP_PROVIDER_CONTRACT_VERSION = "oha-yachiyo.desktop-provider.v1"

OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS = (
    "desktop.list_apps",
    "app.open",
    "desktop.inspect_app",
    "media.music_app_open_and_play",
    "media.music_app_control",
    "desktop.read_ui",
    "desktop.click_ui_element",
    "desktop.safe_type_text",
    "desktop.safe_shortcut",
    "desktop.verify",
)

VIRTUAL_DESKTOP_PROVIDER_TEMPLATE_BASE_URL = "http://127.0.0.1:29097"

_CHECK_BLOCKERS = {
    "provider_configured": "desktop_execution_provider_not_configured",
    "provider_available": "desktop_execution_provider_unavailable",
    "adapter_ready": "desktop_execution_provider_adapter_unavailable",
    "authentication_configured": "desktop_provider_authentication_required",
    "desktop_session_isolated": "desktop_session_not_isolated",
    "foreground_takeover_not_required": "foreground_takeover_required",
    "desktop_backend_declared": "desktop_backend_kind_missing",
    "desktop_backend_not_loopback": "loopback_desktop_backend",
    "desktop_backend_ready_for_public_release": "desktop_backend_not_release_ready",
    "real_virtual_desktop_backend_not_required": "real_virtual_desktop_backend_required",
    "required_tools_supported": "desktop_provider_missing_required_tools",
    "tool_results_present": "desktop_provider_tool_results_missing",
    "all_tools_routed": "desktop_provider_tool_not_routed",
    "all_tool_results_ok": "desktop_provider_tool_result_failed",
    "all_tool_results_isolated": "desktop_provider_tool_result_not_isolated",
    "tool_sequence_covers_required_tools": "desktop_provider_smoke_incomplete",
}

_MANIFEST_CHECK_BLOCKERS = {
    "manifest_present": "desktop_provider_manifest_missing",
    "contract_version_current": "desktop_provider_manifest_contract_version_mismatch",
    "provider_id_present": "desktop_provider_manifest_provider_id_missing",
    "provider_kind_sandbox_desktop": "desktop_provider_manifest_wrong_provider_kind",
    "runtime_endpoint_or_entrypoint_configured": (
        "desktop_provider_manifest_endpoint_or_entrypoint_missing"
    ),
    "local_endpoint_or_remote_allowed": "desktop_provider_manifest_remote_endpoint_not_allowed",
    "status_endpoint_configured": "desktop_provider_manifest_status_endpoint_missing",
    "execute_endpoint_configured": "desktop_provider_manifest_execute_endpoint_missing",
    "release_contract_fields_ready": "virtual_desktop_provider_contract_not_ready",
}


def virtual_desktop_provider_manifest_template(
    *,
    provider_id: str = "oha-virtual-desktop-provider",
    base_url: str = VIRTUAL_DESKTOP_PROVIDER_TEMPLATE_BASE_URL,
) -> dict[str, Any]:
    """Return the manifest shape a real isolated desktop backend must implement."""

    clean_provider_id = str(provider_id or "oha-virtual-desktop-provider").strip()
    clean_base_url = str(base_url or VIRTUAL_DESKTOP_PROVIDER_TEMPLATE_BASE_URL).strip()
    endpoints = {
        "status": "/status",
        "health": "/health",
        "manifest": "/manifest",
        "execute": "/tools/execute",
    }
    endpoint_urls = {
        key: _join_url(clean_base_url, path) for key, path in endpoints.items()
    }
    return {
        "ok": True,
        "contract_version": DESKTOP_PROVIDER_CONTRACT_VERSION,
        "provider_id": clean_provider_id,
        "provider_kind": "sandbox_desktop",
        "execution_mode": "virtual_desktop",
        "url": clean_base_url,
        "base_url": clean_base_url,
        "endpoints": endpoints,
        "endpoint_urls": endpoint_urls,
        "supported_tools": list(OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS),
        "capabilities": [
            "desktop_discovery",
            "app_launch",
            "foreground_mutation",
            "foreground_input",
            "keyboard_mouse_capture",
            "isolated_desktop",
            "virtual_desktop",
            "sandbox_desktop_session",
            "idempotent_tool_requests",
            "permission_diagnostics",
        ],
        "foreground_mutation_supported": True,
        "keyboard_mouse_capture_supported": True,
        "desktop_session_kind": "virtual_desktop",
        "desktop_session_isolated": True,
        "foreground_takeover_required": False,
        "desktop_backend_kind": "virtual_desktop_backend",
        "desktop_backend_is_loopback": False,
        "desktop_backend_ready_for_public_release": True,
        "requires_real_virtual_desktop_backend": False,
        "allow_remote": False,
        "authentication": {
            "token_env": "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN",
        },
        "environment": {
            "manifest": "OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST",
            "url": "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
            "provider_id": "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
            "provider_kind": "OHA_YACHIYO_DESKTOP_PROVIDER_KIND",
            "tools": "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
            "token": "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN",
        },
        "entrypoint": {
            "argv": [
                "/absolute/path/to/virtual-desktop-provider",
                "--host",
                "127.0.0.1",
                "--port",
                "29097",
            ],
            "cwd": ".",
        },
        "smoke_command": [
            "python",
            "scripts/smoke_oha_desktop_agent_release.py",
            "--run-isolated-provider-smoke",
            "--use-configured-virtual-desktop-provider",
            "--provider-manifest",
            "/absolute/path/to/provider-manifest.json",
            "--report-json",
            "tmp/oha-desktop-agent-release-smoke.json",
        ],
        "validate_command": [
            "python",
            "scripts/smoke_oha_desktop_agent_release.py",
            "--validate-provider-manifest",
            "/absolute/path/to/provider-manifest.json",
        ],
        "safety": {
            "loopback_default": False,
            "remote_default_allowed": False,
            "foreground_mutation_tools_supported": True,
            "keyboard_mouse_capture_supported": True,
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "desktop_backend_kind": "virtual_desktop_backend",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": True,
            "requires_real_virtual_desktop_backend": False,
            "requires_runtime_approval": True,
            "approval_required_tools": [
                "desktop.click_ui_element",
                "desktop.safe_shortcut",
                "desktop.safe_type_text",
            ],
        },
    }


def virtual_desktop_provider_manifest_contract_evidence(
    manifest: Mapping[str, Any] | None,
    *,
    required_tools: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return static release-readiness evidence for a provider manifest."""

    manifest_payload = dict(manifest or {})
    required = _string_list(required_tools) or list(
        OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS
    )
    provider_kind = str(
        manifest_payload.get("provider_kind") or "sandbox_desktop"
    ).strip()
    status_url = _manifest_endpoint_url(manifest_payload, "status")
    execute_url = _manifest_endpoint_url(manifest_payload, "execute")
    has_entrypoint = _manifest_entrypoint_configured(manifest_payload)
    endpoint_urls = _manifest_endpoint_urls(manifest_payload)
    remote_endpoint_urls = [
        url
        for url in endpoint_urls
        if not _manifest_endpoint_url_is_local(url)
    ]
    remote_allowed = _optional_bool(manifest_payload.get("allow_remote")) is True
    contract_status = {
        **_manifest_release_status_payload(manifest_payload),
        "configured": bool(manifest_payload),
        "available": True,
        "adapter_ready": True,
    }
    release_contract = virtual_desktop_provider_contract_evidence(
        contract_status,
        required_tools=required,
    )
    checks = {
        "manifest_present": bool(manifest_payload),
        "contract_version_current": (
            str(
                manifest_payload.get("contract_version")
                or manifest_payload.get("version")
                or ""
            ).strip()
            == DESKTOP_PROVIDER_CONTRACT_VERSION
        ),
        "provider_id_present": bool(
            str(manifest_payload.get("provider_id") or "").strip()
        ),
        "provider_kind_sandbox_desktop": (
            provider_kind.lower().replace("-", "_") == "sandbox_desktop"
        ),
        "runtime_endpoint_or_entrypoint_configured": bool(
            status_url or execute_url or has_entrypoint
        ),
        "local_endpoint_or_remote_allowed": remote_allowed
        or not remote_endpoint_urls,
        "status_endpoint_configured": bool(status_url or has_entrypoint),
        "execute_endpoint_configured": bool(execute_url or has_entrypoint),
        "release_contract_fields_ready": release_contract.get("ok") is True,
    }
    manifest_blockers = [
        _MANIFEST_CHECK_BLOCKERS[key]
        for key, passed in checks.items()
        if not passed and key in _MANIFEST_CHECK_BLOCKERS
    ]
    blocking_conditions = _unique_strings(
        [
            *manifest_blockers,
            *release_contract.get("blocking_conditions", []),
        ]
    )
    manifest_ok = all(checks.values())
    conformance_contract = {
        **release_contract,
        "ok": manifest_ok,
        "blocking_conditions": blocking_conditions,
    }
    return {
        "ok": manifest_ok,
        "contract_version": DESKTOP_PROVIDER_CONTRACT_VERSION,
        "runtime_checked": False,
        "checks": checks,
        "blocking_conditions": blocking_conditions,
        "manifest_blocking_conditions": manifest_blockers,
        "release_contract": release_contract,
        "provider_conformance": virtual_desktop_provider_conformance_summary(
            conformance_contract,
            status=contract_status,
            mode="manifest_contract_check",
            runtime_checked=False,
        ),
        "missing_required_tools": release_contract.get("missing_required_tools", []),
        "required_tools": required,
        "provider_id": str(manifest_payload.get("provider_id") or "").strip(),
        "provider_kind": provider_kind,
        "status_url": status_url,
        "execute_url": execute_url,
        "endpoint_urls": endpoint_urls,
        "remote_endpoint_urls": remote_endpoint_urls,
        "remote_endpoint_allowed": remote_allowed,
        "entrypoint_configured": has_entrypoint,
    }


def virtual_desktop_provider_conformance_summary(
    provider_contract: Mapping[str, Any] | None = None,
    *,
    status: Mapping[str, Any] | None = None,
    mode: str = "provider_contract_check",
    runtime_checked: bool = False,
    release_candidate: bool | None = None,
    public_release_ready: bool | None = None,
    smoke_ok: bool | None = None,
    supported_tools: Sequence[str] | None = None,
    failed_tools: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return the public provider conformance shape shared by Studio and release gates."""

    contract = dict(provider_contract or {})
    status_payload = dict(status or {})
    if not contract:
        contract = virtual_desktop_provider_contract_evidence(
            status_payload,
            required_tools=OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
        )
    contract_ok = bool(contract.get("ok"))
    required = _string_list(contract.get("required_tools")) or list(
        OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS
    )
    supported = set(
        _string_list(supported_tools)
        or _string_list(contract.get("supported_tools"))
        or _string_list(status_payload.get("supported_tools"))
    )
    blockers = _string_list(contract.get("blocking_conditions"))
    return {
        "ok": contract_ok,
        "mode": str(mode or "provider_contract_check").strip(),
        "runtime_checked": bool(runtime_checked),
        "release_candidate": (
            contract_ok if release_candidate is None else bool(release_candidate)
        ),
        "public_release_ready": (
            contract_ok if public_release_ready is None else bool(public_release_ready)
        ),
        "smoke_ok": smoke_ok if isinstance(smoke_ok, bool) else None,
        "provider_contract_ok": contract_ok,
        "required_tools": required,
        "covered_tools": [tool for tool in required if tool in supported],
        "missing_required_tools": _string_list(contract.get("missing_required_tools")),
        "failed_tools": _string_list(failed_tools),
        "blocking_conditions": blockers,
        "release_blocking_conditions": blockers,
        "provider_contract_blocking_conditions": blockers,
        "desktop_session_kind": _first_text(
            contract.get("desktop_session_kind"),
            status_payload.get("desktop_session_kind"),
        ),
        "desktop_session_isolated": _optional_bool(
            contract.get("desktop_session_isolated")
            if "desktop_session_isolated" in contract
            else status_payload.get("desktop_session_isolated")
        ),
        "foreground_takeover_required": _optional_bool(
            contract.get("foreground_takeover_required")
            if "foreground_takeover_required" in contract
            else status_payload.get("foreground_takeover_required")
        ),
        "authentication_configured": bool(
            contract.get("authentication_configured")
            if "authentication_configured" in contract
            else status_payload.get("authentication_configured")
        ),
        "desktop_backend_kind": _first_text(
            contract.get("desktop_backend_kind"),
            status_payload.get("desktop_backend_kind"),
        ),
        "desktop_backend_is_loopback": _optional_bool(
            contract.get("desktop_backend_is_loopback")
            if "desktop_backend_is_loopback" in contract
            else status_payload.get("desktop_backend_is_loopback")
        ),
        "desktop_backend_ready_for_public_release": _optional_bool(
            contract.get("desktop_backend_ready_for_public_release")
            if "desktop_backend_ready_for_public_release" in contract
            else status_payload.get("desktop_backend_ready_for_public_release")
        ),
        "requires_real_virtual_desktop_backend": _optional_bool(
            contract.get("requires_real_virtual_desktop_backend")
            if "requires_real_virtual_desktop_backend" in contract
            else status_payload.get("requires_real_virtual_desktop_backend")
        ),
    }


def virtual_desktop_provider_contract_evidence(
    status: Mapping[str, Any] | None,
    *,
    required_tools: Sequence[str] | None = None,
    tool_results: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return release-readiness evidence for a Hermes/Hanako-style desktop backend."""

    status_payload = dict(status or {})
    required = _string_list(required_tools)
    supported = _supported_tools(status_payload)
    desktop_backend_kind = str(status_payload.get("desktop_backend_kind") or "").strip()
    checks = {
        "provider_configured": status_payload.get("configured") is True,
        "provider_available": bool(status_payload.get("available")),
        "adapter_ready": bool(status_payload.get("adapter_ready")),
        "authentication_configured": _authentication_configured(status_payload),
        "desktop_session_isolated": _desktop_session_isolated(status_payload),
        "foreground_takeover_not_required": (
            _optional_bool(status_payload.get("foreground_takeover_required")) is False
        ),
        "desktop_backend_declared": bool(desktop_backend_kind),
        "desktop_backend_not_loopback": (
            _optional_bool(status_payload.get("desktop_backend_is_loopback")) is False
        ),
        "desktop_backend_ready_for_public_release": (
            _optional_bool(
                status_payload.get("desktop_backend_ready_for_public_release")
            )
            is True
        ),
        "real_virtual_desktop_backend_not_required": (
            _optional_bool(status_payload.get("requires_real_virtual_desktop_backend"))
            is False
        ),
        "required_tools_supported": not required or set(required).issubset(supported),
    }
    if tool_results is not None:
        result_list = [dict(item) for item in tool_results if isinstance(item, Mapping)]
        result_tools = {
            str(item.get("tool") or item.get("action") or "").strip()
            for item in result_list
        }
        checks.update(
            {
                "tool_results_present": bool(result_list),
                "all_tools_routed": all(
                    item.get("desktop_execution_provider_routed") is True
                    for item in result_list
                ),
                "all_tool_results_ok": all(
                    item.get("ok") is not False for item in result_list
                ),
                "all_tool_results_isolated": all(
                    _tool_result_reports_isolated_session(item) for item in result_list
                ),
                "tool_sequence_covers_required_tools": (
                    not required or set(required).issubset(result_tools)
                ),
            }
        )
    blockers = [
        _CHECK_BLOCKERS[key]
        for key, passed in checks.items()
        if not passed and key in _CHECK_BLOCKERS
    ]
    missing_tools = sorted(set(required) - supported)
    return {
        "ok": all(checks.values()),
        "contract_version": DESKTOP_PROVIDER_CONTRACT_VERSION,
        "checks": checks,
        "blocking_conditions": blockers,
        "missing_required_tools": missing_tools,
        "required_tools": required,
        "supported_tools": sorted(supported),
        "desktop_session_kind": str(
            status_payload.get("desktop_session_kind") or ""
        ).strip(),
        "desktop_session_isolated": _desktop_session_isolated(status_payload),
        "foreground_takeover_required": _optional_bool(
            status_payload.get("foreground_takeover_required")
        ),
        "keyboard_mouse_capture_supported": _optional_bool(
            status_payload.get("keyboard_mouse_capture_supported")
        ),
        "authentication_configured": _authentication_configured(status_payload),
        "desktop_backend_kind": desktop_backend_kind,
        "desktop_backend_is_loopback": _optional_bool(
            status_payload.get("desktop_backend_is_loopback")
        ),
        "desktop_backend_ready_for_public_release": _optional_bool(
            status_payload.get("desktop_backend_ready_for_public_release")
        ),
        "requires_real_virtual_desktop_backend": _optional_bool(
            status_payload.get("requires_real_virtual_desktop_backend")
        ),
    }


def _desktop_session_isolated(status: Mapping[str, Any]) -> bool:
    session_isolated = _optional_bool(status.get("desktop_session_isolated"))
    if session_isolated is not None:
        return session_isolated
    return str(status.get("desktop_session_kind") or "").strip() in {
        "isolated_desktop",
        "virtual_desktop",
    }


def _authentication_configured(status: Mapping[str, Any]) -> bool:
    explicit = _optional_bool(status.get("authentication_configured"))
    if explicit is not None:
        return explicit
    authentication = _mapping(status.get("authentication"))
    return bool(
        status.get("token")
        or status.get("token_env")
        or authentication.get("token")
        or authentication.get("token_env")
    )


def _supported_tools(status: Mapping[str, Any]) -> set[str]:
    health = status.get("health")
    health_tools = (
        _string_list(health.get("supported_tools"))
        if isinstance(health, Mapping)
        else []
    )
    return set(_string_list(status.get("supported_tools")) or health_tools)


def _tool_result_reports_isolated_session(item: Mapping[str, Any]) -> bool:
    isolated_provider = item.get("isolated_desktop_provider")
    if (
        isinstance(isolated_provider, Mapping)
        and _optional_bool(isolated_provider.get("desktop_session_isolated")) is True
    ):
        return True
    sandbox_provider = item.get("sandbox_provider")
    return (
        isinstance(sandbox_provider, Mapping)
        and _optional_bool(sandbox_provider.get("desktop_session_isolated")) is True
    )


def _optional_bool(value: Any) -> bool | None:
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
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw = value
    else:
        raw = []
    return [str(item or "").strip() for item in raw if str(item or "").strip()]


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _join_url(base_url: str, path: str) -> str:
    clean_base = str(base_url or "").rstrip("/")
    clean_path = "/" + str(path or "").lstrip("/")
    return f"{clean_base}{clean_path}" if clean_base else clean_path


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _manifest_release_status_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    safety = _mapping(manifest.get("safety"))
    payload: dict[str, Any] = {}
    for key in (
        "supported_tools",
        "desktop_session_kind",
        "desktop_session_isolated",
        "foreground_takeover_required",
        "keyboard_mouse_capture_supported",
        "desktop_backend_kind",
        "desktop_backend_is_loopback",
        "desktop_backend_ready_for_public_release",
        "requires_real_virtual_desktop_backend",
    ):
        payload[key] = manifest.get(key) if key in manifest else safety.get(key)
    authentication = _mapping(manifest.get("authentication"))
    payload["authentication_configured"] = bool(
        manifest.get("token")
        or manifest.get("token_env")
        or authentication.get("token")
        or authentication.get("token_env")
    )
    return payload


def _manifest_endpoint_url(manifest: Mapping[str, Any], purpose: str) -> str:
    base_url = _manifest_base_url(manifest)
    endpoint_urls = _mapping(manifest.get("endpoint_urls"))
    endpoints = _mapping(manifest.get("endpoints"))
    if purpose == "execute":
        candidates = (
            "execute",
            "tools_execute",
            "tools.execute",
            "tools/execute",
            "execute_url",
        )
        default_path = "/tools/execute"
    else:
        candidates = ("status", "health", "status_url")
        default_path = "/status"
    raw = _first_mapping_value(endpoint_urls, *candidates) or _first_mapping_value(
        endpoints,
        *candidates,
    )
    if raw:
        value = str(raw or "").strip()
        if value.startswith(("http://", "https://")):
            return value
        return _join_url(base_url, value) if base_url else value
    return _join_url(base_url, default_path) if base_url else ""


def _manifest_endpoint_urls(manifest: Mapping[str, Any]) -> list[str]:
    endpoint_urls = _mapping(manifest.get("endpoint_urls"))
    urls = [
        _manifest_base_url(manifest),
        _manifest_endpoint_url(manifest, "status"),
        _manifest_endpoint_url(manifest, "execute"),
        *[
            str(value or "").strip()
            for value in endpoint_urls.values()
            if str(value or "").strip()
        ],
    ]
    return _unique_strings(urls)


def _manifest_endpoint_url_is_local(url: str) -> bool:
    value = str(url or "").strip()
    if not value:
        return True
    parsed = urlparse(value)
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        return True
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _manifest_base_url(manifest: Mapping[str, Any]) -> str:
    endpoint_urls = _mapping(manifest.get("endpoint_urls"))
    direct = _first_mapping_value(manifest, "url", "endpoint_origin", "base_url")
    nested = _first_mapping_value(endpoint_urls, "url", "base_url", "base", "origin")
    if direct or nested:
        return str(direct or nested or "").strip().rstrip("/")
    for key in ("execute", "status", "health", "execute_url", "status_url"):
        origin = _url_origin(str(endpoint_urls.get(key) or ""))
        if origin:
            return origin
    return ""


def _manifest_entrypoint_configured(manifest: Mapping[str, Any]) -> bool:
    entrypoint = _mapping(manifest.get("entrypoint"))
    command = entrypoint.get("command") or entrypoint.get("argv")
    if isinstance(command, str) and command.strip():
        return True
    if isinstance(command, Sequence) and not isinstance(command, (str, bytes, bytearray)):
        return any(str(item or "").strip() for item in command)
    return bool(
        str(entrypoint.get("script") or "").strip()
        or str(entrypoint.get("module") or "").strip()
    )


def _first_mapping_value(mapping: Mapping[str, Any], *keys: str) -> Any:
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


def _unique_strings(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        result.append(item)
        seen.add(item)
    return result
