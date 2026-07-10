"""Agent Studio diagnostics for the controlled desktop provider."""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from apps.shell.agent.runtime.controlled_desktop_provider import ControlledDesktopProvider
from apps.shell.agent.runtime.desktop_execution_providers import (
    desktop_execution_provider_status_from_env,
)
from apps.shell.agent.runtime.desktop_provider_credentials import (
    desktop_provider_token_from_manifest,
)
from apps.shell.agent.runtime.isolated_desktop_provider import IsolatedDesktopProvider

from .contracts import (
    ControlledDesktopProviderDiagnosticSnapshot,
    DesktopProviderHealthSnapshot,
    SandboxDesktopProviderSnapshot,
)
from .desktop_provider_contract import (
    OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    virtual_desktop_provider_conformance_summary,
    virtual_desktop_provider_contract_evidence,
)
from .desktop_provider_release_readiness import public_release_readiness_snapshot
from .desktop_execution_policy import sandbox_desktop_provider_status
from .isolated_provider_session import isolated_desktop_provider_session_status

_PROVIDER_MANIFEST_ENV = "OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST"


def controlled_desktop_provider_diagnostics_snapshot(
    *,
    sandbox_provider: Mapping[str, Any] | SandboxDesktopProviderSnapshot | None = None,
) -> ControlledDesktopProviderDiagnosticSnapshot:
    """Describe whether the Hermes/Hanako-style control provider is usable."""

    provider_payload = _provider_payload(sandbox_provider)
    provider = SandboxDesktopProviderSnapshot.model_validate(provider_payload)
    session_manager = isolated_desktop_provider_session_status()
    env_status = desktop_execution_provider_status_from_env(probe_health=False)
    runtime_status = _diagnostic_runtime_status(env_status, session_manager)
    launch_hint = _mapping(provider.launch_hint)
    controlled_launch = _mapping(
        launch_hint.get("isolated_provider") or launch_hint.get("controlled_provider")
    )
    controlled_env = _string_mapping(controlled_launch.get("env"))
    provider_manifest_path = str(os.environ.get(_PROVIDER_MANIFEST_ENV) or "").strip()
    configured_manifest = _configured_provider_manifest()
    manifest_provider = (
        IsolatedDesktopProvider()
        if controlled_launch.get("desktop_session_isolated") is not False
        else ControlledDesktopProvider()
    )
    fallback_manifest = manifest_provider.manifest(
        base_url=controlled_env.get("OHA_YACHIYO_DESKTOP_PROVIDER_URL", "")
    )
    manifest = configured_manifest or fallback_manifest
    configured = bool(runtime_status.get("configured"))
    if sandbox_provider is None and configured:
        provider_overlay = {
            key: value
            for key, value in runtime_status.items()
            if key in SandboxDesktopProviderSnapshot.model_fields
        }
        provider = SandboxDesktopProviderSnapshot.model_validate(
            {
                **provider_payload,
                **provider_overlay,
                "source": _diagnostic_source(
                    configured=configured,
                    configured_manifest=bool(configured_manifest),
                    runtime_status=runtime_status,
                    session_manager=session_manager,
                ),
            }
        )
    manifest_safety = _mapping(manifest.get("safety"))
    if configured:
        foreground_mutation_supported = _optional_bool(
            provider.foreground_mutation_supported,
            _nested_bool(provider.health, "foreground_mutation_supported"),
            runtime_status.get("foreground_mutation_supported"),
            controlled_launch.get("foreground_mutation_supported"),
            manifest.get("foreground_mutation_supported"),
        )
        keyboard_mouse_capture_supported = _optional_bool(
            provider.keyboard_mouse_capture_supported,
            _nested_bool(provider.health, "keyboard_mouse_capture_supported"),
            runtime_status.get("keyboard_mouse_capture_supported"),
            controlled_launch.get("keyboard_mouse_capture_supported"),
            manifest.get("keyboard_mouse_capture_supported"),
        )
    else:
        foreground_mutation_supported = _optional_bool(
            controlled_launch.get("foreground_mutation_supported"),
            manifest.get("foreground_mutation_supported"),
            manifest_safety.get("foreground_mutation_supported"),
            provider.foreground_mutation_supported,
            _nested_bool(provider.health, "foreground_mutation_supported"),
        )
        keyboard_mouse_capture_supported = _optional_bool(
            controlled_launch.get("keyboard_mouse_capture_supported"),
            manifest.get("keyboard_mouse_capture_supported"),
            manifest_safety.get("keyboard_mouse_capture_supported"),
            provider.keyboard_mouse_capture_supported,
            _nested_bool(provider.health, "keyboard_mouse_capture_supported"),
        )
    if configured:
        desktop_session_kind = (
            str(provider.desktop_session_kind or "").strip()
            or _nested_text(provider.health, "desktop_session_kind")
            or str(runtime_status.get("desktop_session_kind") or "").strip()
            or str(controlled_launch.get("desktop_session_kind") or "").strip()
            or str(manifest.get("desktop_session_kind") or "").strip()
            or str(manifest_safety.get("desktop_session_kind") or "").strip()
        )
        desktop_session_isolated = _optional_bool(
            provider.desktop_session_isolated,
            _nested_bool(provider.health, "desktop_session_isolated"),
            runtime_status.get("desktop_session_isolated"),
            controlled_launch.get("desktop_session_isolated"),
            manifest.get("desktop_session_isolated"),
            manifest_safety.get("desktop_session_isolated"),
        )
        foreground_takeover_required = _optional_bool(
            provider.foreground_takeover_required,
            _nested_bool(provider.health, "foreground_takeover_required"),
            runtime_status.get("foreground_takeover_required"),
            controlled_launch.get("foreground_takeover_required"),
            manifest.get("foreground_takeover_required"),
            manifest_safety.get("foreground_takeover_required"),
        )
    else:
        desktop_session_kind = (
            str(controlled_launch.get("desktop_session_kind") or "").strip()
            or str(manifest.get("desktop_session_kind") or "").strip()
            or str(manifest_safety.get("desktop_session_kind") or "").strip()
            or str(provider.desktop_session_kind or "").strip()
            or _nested_text(provider.health, "desktop_session_kind")
        )
        desktop_session_isolated = _optional_bool(
            controlled_launch.get("desktop_session_isolated"),
            manifest.get("desktop_session_isolated"),
            manifest_safety.get("desktop_session_isolated"),
            provider.desktop_session_isolated,
            _nested_bool(provider.health, "desktop_session_isolated"),
        )
        foreground_takeover_required = _optional_bool(
            controlled_launch.get("foreground_takeover_required"),
            manifest.get("foreground_takeover_required"),
            manifest_safety.get("foreground_takeover_required"),
            provider.foreground_takeover_required,
            _nested_bool(provider.health, "foreground_takeover_required"),
        )
    desktop_backend_kind = _first_text(
        provider.desktop_backend_kind,
        _nested_text(provider.health, "desktop_backend_kind"),
        runtime_status.get("desktop_backend_kind"),
        controlled_launch.get("desktop_backend_kind"),
        manifest.get("desktop_backend_kind"),
        manifest_safety.get("desktop_backend_kind"),
    )
    desktop_backend_is_loopback = _optional_bool(
        provider.desktop_backend_is_loopback,
        _nested_bool(provider.health, "desktop_backend_is_loopback"),
        runtime_status.get("desktop_backend_is_loopback"),
        controlled_launch.get("desktop_backend_is_loopback"),
        manifest.get("desktop_backend_is_loopback"),
        manifest_safety.get("desktop_backend_is_loopback"),
    )
    desktop_backend_ready_for_public_release = _optional_bool(
        provider.desktop_backend_ready_for_public_release,
        _nested_bool(provider.health, "desktop_backend_ready_for_public_release"),
        runtime_status.get("desktop_backend_ready_for_public_release"),
        controlled_launch.get("desktop_backend_ready_for_public_release"),
        manifest.get("desktop_backend_ready_for_public_release"),
        manifest_safety.get("desktop_backend_ready_for_public_release"),
    )
    requires_real_virtual_desktop_backend = _optional_bool(
        provider.requires_real_virtual_desktop_backend,
        _nested_bool(provider.health, "requires_real_virtual_desktop_backend"),
        runtime_status.get("requires_real_virtual_desktop_backend"),
        controlled_launch.get("requires_real_virtual_desktop_backend"),
        manifest.get("requires_real_virtual_desktop_backend"),
        manifest_safety.get("requires_real_virtual_desktop_backend"),
    )
    supported_tools = (
        _string_list(provider.supported_tools) if configured else []
    ) or _string_list(manifest.get("supported_tools"))
    capabilities = (
        _string_list(provider.health.capabilities if provider.health else [])
        or _string_list(runtime_status.get("capabilities"))
        or _string_list(manifest.get("capabilities"))
    )
    authentication_configured = bool(
        provider.authentication_configured
        or runtime_status.get("authentication_configured")
        or desktop_provider_token_from_manifest(manifest)
    )
    provider_contract = virtual_desktop_provider_contract_evidence(
        {
            "configured": configured,
            "available": provider.available,
            "adapter_ready": provider.adapter_ready,
            "authentication_configured": authentication_configured,
            "capabilities": capabilities,
            "desktop_session_kind": desktop_session_kind,
            "desktop_session_isolated": desktop_session_isolated,
            "foreground_takeover_required": foreground_takeover_required,
            "desktop_backend_kind": desktop_backend_kind,
            "desktop_backend_is_loopback": desktop_backend_is_loopback,
            "desktop_backend_ready_for_public_release": (
                desktop_backend_ready_for_public_release
            ),
            "requires_real_virtual_desktop_backend": (
                requires_real_virtual_desktop_backend
            ),
            "supported_tools": supported_tools,
        },
        required_tools=OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    )
    release_ready = bool(provider_contract.get("ok"))
    ready = (
        configured
        and provider.available
        and provider.adapter_ready
        and str(provider.provider_kind or "") == "sandbox_desktop"
        and keyboard_mouse_capture_supported is True
        and desktop_session_isolated is True
        and release_ready
    )
    status = _diagnostic_status(
        ready=ready,
        configured=configured,
        provider=provider,
        keyboard_mouse_capture_supported=keyboard_mouse_capture_supported,
        desktop_session_isolated=desktop_session_isolated,
        provider_contract=provider_contract,
    )
    blocking_conditions = _diagnostic_blockers(
        ready=ready,
        configured=configured,
        provider=provider,
        keyboard_mouse_capture_supported=keyboard_mouse_capture_supported,
        desktop_session_isolated=desktop_session_isolated,
        provider_contract=provider_contract,
    )
    provider_conformance = virtual_desktop_provider_conformance_summary(
        provider_contract,
        status=provider_contract,
        mode="provider_diagnostics_contract_check",
        runtime_checked=configured,
        release_candidate=ready,
        public_release_ready=release_ready,
        supported_tools=supported_tools,
    )
    public_release_readiness = public_release_readiness_snapshot(
        run_isolated_provider_smoke=False,
        configured_virtual_desktop_provider_requested=(
            configured or bool(provider_manifest_path)
        ),
        provider_manifest=provider_manifest_path,
        release_ready=ready,
        release_blockers=blocking_conditions,
        backend=_public_release_backend_evidence(
            provider_contract=provider_contract,
            provider_conformance=provider_conformance,
            desktop_backend_kind=desktop_backend_kind,
            desktop_backend_is_loopback=desktop_backend_is_loopback,
            desktop_backend_ready_for_public_release=(
                desktop_backend_ready_for_public_release
            ),
            requires_real_virtual_desktop_backend=(
                requires_real_virtual_desktop_backend
            ),
        ),
    )
    return ControlledDesktopProviderDiagnosticSnapshot(
        ready=ready,
        release_ready=release_ready,
        configured=configured,
        authentication_configured=authentication_configured,
        status=status,
        provider_id=_diagnostic_provider_id(
            configured=configured,
            provider=provider,
            env_status=runtime_status,
            controlled_launch=controlled_launch,
            manifest=manifest,
        ),
        provider_kind="sandbox_desktop",
        execution_mode=str(
            controlled_launch.get("execution_mode")
            or manifest.get("execution_mode")
            or "controlled_desktop"
        ),
        source=_diagnostic_source(
            configured=configured,
            configured_manifest=bool(configured_manifest),
            runtime_status=runtime_status,
            session_manager=session_manager,
        ),
        reason=_diagnostic_reason(
            ready=ready,
            configured=configured,
            provider=provider,
            keyboard_mouse_capture_supported=keyboard_mouse_capture_supported,
            desktop_session_isolated=desktop_session_isolated,
            provider_contract=provider_contract,
        ),
        blocking_conditions=blocking_conditions,
        supported_tools=supported_tools,
        capabilities=capabilities,
        foreground_mutation_supported=foreground_mutation_supported,
        keyboard_mouse_capture_supported=keyboard_mouse_capture_supported,
        desktop_session_kind=desktop_session_kind,
        desktop_session_isolated=desktop_session_isolated,
        foreground_takeover_required=foreground_takeover_required,
        desktop_backend_kind=desktop_backend_kind,
        desktop_backend_is_loopback=desktop_backend_is_loopback,
        desktop_backend_ready_for_public_release=(
            desktop_backend_ready_for_public_release
        ),
        requires_real_virtual_desktop_backend=requires_real_virtual_desktop_backend,
        provider_contract=provider_contract,
        provider_conformance=provider_conformance,
        requires_real_sandbox_for=_string_list(provider.requires_real_sandbox_for),
        requires_runtime_approval=bool(
            controlled_launch.get("requires_runtime_approval")
            if "requires_runtime_approval" in controlled_launch
            else _mapping(manifest.get("safety")).get("requires_runtime_approval", True)
        ),
        approval_required_tools=_string_list(
            _mapping(manifest.get("safety")).get("approval_required_tools")
        ),
        launch_command=(
            _entrypoint_command(manifest) if configured_manifest else []
        )
        or _string_list(controlled_launch.get("command"))
        or _entrypoint_command(manifest),
        smoke_command=(
            _string_list(manifest.get("smoke_command")) if configured_manifest else []
        )
        or _string_list(controlled_launch.get("smoke_command"))
        or _string_list(manifest.get("smoke_command")),
        env=controlled_env,
        endpoint_origin=str(
            runtime_status.get("endpoint_origin") or _manifest_endpoint_origin(manifest)
        ),
        endpoint_path=str(runtime_status.get("endpoint_path") or ""),
        status_endpoint_path=str(runtime_status.get("status_endpoint_path") or ""),
        health=provider.health,
        manifest=manifest,
        session_manager=session_manager,
        public_release_readiness=public_release_readiness,
    )


def controlled_desktop_provider_diagnostics_payload(
    *,
    sandbox_provider: Mapping[str, Any] | SandboxDesktopProviderSnapshot | None = None,
) -> dict[str, Any]:
    return controlled_desktop_provider_diagnostics_snapshot(
        sandbox_provider=sandbox_provider,
    ).model_dump(mode="json")


def _provider_payload(
    sandbox_provider: Mapping[str, Any] | SandboxDesktopProviderSnapshot | None,
) -> dict[str, Any]:
    if isinstance(sandbox_provider, SandboxDesktopProviderSnapshot):
        return sandbox_provider.model_dump(mode="json")
    if isinstance(sandbox_provider, Mapping):
        return sandbox_desktop_provider_status({"sandbox_provider": dict(sandbox_provider)})
    return sandbox_desktop_provider_status(
        {
            "desktop_provider_health_probe": True,
            "desktop_provider_local_native": True,
        }
    )


def _diagnostic_runtime_status(
    env_status: Mapping[str, Any],
    session_manager: Mapping[str, Any],
) -> dict[str, Any]:
    session_provider_status = _mapping(session_manager.get("provider_status"))
    if session_provider_status.get("configured") is True:
        return session_provider_status
    return dict(env_status)


def _diagnostic_source(
    *,
    configured: bool,
    configured_manifest: bool,
    runtime_status: Mapping[str, Any],
    session_manager: Mapping[str, Any],
) -> str:
    if configured:
        session_source = str(session_manager.get("source") or "").strip()
        if session_source == "provider_manifest":
            return "provider_manifest"
        return str(runtime_status.get("source") or session_source or "runtime_env")
    return "provider_manifest" if configured_manifest else "launch_hint"


def _diagnostic_status(
    *,
    ready: bool,
    configured: bool,
    provider: SandboxDesktopProviderSnapshot,
    keyboard_mouse_capture_supported: bool | None,
    desktop_session_isolated: bool | None,
    provider_contract: Mapping[str, Any],
) -> str:
    if ready:
        return "ready"
    if not configured:
        if desktop_session_isolated is True:
            return "isolated_provider_required"
        return "controlled_provider_required"
    if keyboard_mouse_capture_supported is not True:
        return "keyboard_mouse_capture_required"
    if desktop_session_isolated is not True:
        return "isolated_desktop_session_required"
    if provider_contract.get("ok") is not True:
        return "virtual_desktop_provider_contract_required"
    return provider.status or "provider_unavailable"


def _diagnostic_blockers(
    *,
    ready: bool,
    configured: bool,
    provider: SandboxDesktopProviderSnapshot,
    keyboard_mouse_capture_supported: bool | None,
    desktop_session_isolated: bool | None,
    provider_contract: Mapping[str, Any],
) -> list[str]:
    if ready:
        return []
    blockers = _string_list(provider.blocking_conditions)
    if not configured:
        blockers.append(
            "isolated_desktop_provider_required"
            if desktop_session_isolated is True
            else "controlled_desktop_provider_required"
        )
    if configured and not provider.adapter_ready:
        blockers.append("sandbox_desktop_adapter_required")
    if keyboard_mouse_capture_supported is not True:
        blockers.append("sandbox_keyboard_mouse_provider_required")
    if desktop_session_isolated is not True:
        blockers.append("sandbox_desktop_session_required")
    blockers.extend(_string_list(provider_contract.get("blocking_conditions")))
    return _unique_strings(blockers)


def _diagnostic_reason(
    *,
    ready: bool,
    configured: bool,
    provider: SandboxDesktopProviderSnapshot,
    keyboard_mouse_capture_supported: bool | None,
    desktop_session_isolated: bool | None,
    provider_contract: Mapping[str, Any],
) -> str:
    if ready:
        return "Controlled desktop provider is configured inside an isolated desktop session."
    if not configured:
        if desktop_session_isolated is True:
            return "Start the isolated desktop provider before autonomous foreground input."
        return "Start the controlled desktop provider before autonomous foreground input."
    if keyboard_mouse_capture_supported is not True:
        return "Configured provider does not advertise keyboard and mouse capture."
    if desktop_session_isolated is not True:
        return "Configured provider controls the user foreground instead of an isolated desktop session."
    if provider_contract.get("ok") is not True:
        blockers = _string_list(provider_contract.get("blocking_conditions"))
        if blockers:
            return (
                "Configured provider is not release-ready: "
                + ", ".join(blockers[:3])
                + "."
            )
        return "Configured provider is not release-ready for public desktop execution."
    return provider.reason or "Controlled desktop provider is configured but not ready."


def _diagnostic_provider_id(
    *,
    configured: bool,
    provider: SandboxDesktopProviderSnapshot,
    env_status: Mapping[str, Any],
    controlled_launch: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> str:
    if configured:
        return str(env_status.get("provider_id") or provider.provider_id or "")
    return str(
        controlled_launch.get("provider_id")
        or manifest.get("provider_id")
        or "local-controlled-desktop"
    )


def _entrypoint_command(manifest: Mapping[str, Any]) -> list[str]:
    entrypoint = _mapping(manifest.get("entrypoint"))
    command = entrypoint.get("command") or entrypoint.get("argv")
    if isinstance(command, str):
        return shlex.split(command)
    if isinstance(command, list):
        return [str(item) for item in command if str(item or "").strip()]
    module = str(entrypoint.get("module") or "").strip()
    args = _string_list(entrypoint.get("args"))
    if module:
        return ["python", "-m", module, *args]
    script = str(entrypoint.get("script") or "").strip()
    return ["python", script, *args] if script else []


def _configured_provider_manifest() -> dict[str, Any]:
    raw_path = str(os.environ.get(_PROVIDER_MANIFEST_ENV) or "").strip()
    if not raw_path:
        return {}
    path = Path(raw_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _public_release_backend_evidence(
    *,
    provider_contract: Mapping[str, Any],
    provider_conformance: Mapping[str, Any],
    desktop_backend_kind: str,
    desktop_backend_is_loopback: bool | None,
    desktop_backend_ready_for_public_release: bool | None,
    requires_real_virtual_desktop_backend: bool | None,
) -> dict[str, Any]:
    return {
        "desktop_backend_kind": desktop_backend_kind,
        "desktop_backend_is_loopback": desktop_backend_is_loopback,
        "desktop_backend_ready_for_public_release": (
            desktop_backend_ready_for_public_release
        ),
        "requires_real_virtual_desktop_backend": (
            requires_real_virtual_desktop_backend
        ),
        "provider_contract_ok": provider_contract.get("ok"),
        "provider_contract_blocking_conditions": _string_list(
            provider_contract.get("blocking_conditions")
        ),
        "provider_conformance_public_release_ready": provider_conformance.get(
            "public_release_ready"
        ),
        "provider_conformance_release_blocking_conditions": _string_list(
            provider_conformance.get("release_blocking_conditions")
        ),
        "provider_conformance_missing_required_tools": _string_list(
            provider_conformance.get("missing_required_tools")
        ),
        "provider_conformance_failed_tools": _string_list(
            provider_conformance.get("failed_tools")
        ),
    }


def _manifest_endpoint_origin(manifest: Mapping[str, Any]) -> str:
    endpoint_urls = _mapping(manifest.get("endpoint_urls"))
    endpoints = _mapping(manifest.get("endpoints"))
    candidates = [
        manifest.get("url"),
        manifest.get("endpoint_origin"),
        manifest.get("base_url"),
        endpoint_urls.get("url"),
        endpoint_urls.get("base_url"),
        endpoint_urls.get("base"),
        endpoint_urls.get("origin"),
        endpoint_urls.get("execute"),
        endpoint_urls.get("status"),
        endpoints.get("execute"),
        endpoints.get("status"),
    ]
    for candidate in candidates:
        origin = _url_origin(str(candidate or ""))
        if origin:
            return origin
    return ""


def _url_origin(value: str) -> str:
    parsed = urlparse(str(value or ""))
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _nested_bool(snapshot: DesktopProviderHealthSnapshot | None, key: str) -> bool | None:
    if snapshot is None:
        return None
    return _optional_bool(getattr(snapshot, key, None))


def _nested_text(snapshot: DesktopProviderHealthSnapshot | None, key: str) -> str:
    if snapshot is None:
        return ""
    return str(getattr(snapshot, key, "") or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _optional_bool(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "no", "n", "off"}:
                return False
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if str(key).strip() and item is not None
    }


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Mapping):
        return []
    try:
        return [str(item).strip() for item in value if str(item).strip()]
    except TypeError:
        return []


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result
