"""Public-release readiness guidance for desktop execution providers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .desktop_provider_contract import OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS


def public_release_readiness_snapshot(
    *,
    run_isolated_provider_smoke: bool,
    configured_virtual_desktop_provider_requested: bool,
    provider_manifest: str | Path | None,
    release_ready: bool,
    release_blockers: Sequence[str] = (),
    backend: Mapping[str, Any] | None = None,
    isolated_desktop_required: bool = True,
) -> dict[str, Any]:
    """Return machine-readable readiness evidence and next actions."""

    clean_manifest = _clean_provider_manifest(provider_manifest)
    backend_payload = dict(backend or {})
    blockers = _unique_strings(release_blockers)
    if not release_ready and not blockers and isolated_desktop_required:
        blockers = _public_release_advisory_blockers(
            configured_virtual_desktop_provider_requested=(
                configured_virtual_desktop_provider_requested
            ),
            backend=backend_payload,
        )
    if (
        isolated_desktop_required
        and not release_ready
        and not configured_virtual_desktop_provider_requested
        and "virtual_desktop_provider_not_configured" not in blockers
    ):
        blockers.append("virtual_desktop_provider_not_configured")
    if not release_ready and not blockers:
        blockers.append("direct_desktop_runtime_not_ready")
    return {
        "ready": bool(release_ready),
        "backend_ready": bool(release_ready),
        "provider_manifest": clean_manifest,
        "configured_virtual_desktop_provider_requested": bool(
            configured_virtual_desktop_provider_requested
        ),
        "blocking_conditions": blockers,
        "backend": backend_payload,
        "next_actions": _public_release_next_actions(
            release_ready=release_ready,
            isolated_desktop_required=isolated_desktop_required,
            run_isolated_provider_smoke=run_isolated_provider_smoke,
            configured_virtual_desktop_provider_requested=(
                configured_virtual_desktop_provider_requested
            ),
            provider_manifest=clean_manifest,
            blockers=blockers,
        ),
        "required_commands": _public_release_required_commands(
            clean_manifest,
            isolated_desktop_required=isolated_desktop_required,
        ),
    }


def _public_release_advisory_blockers(
    *,
    configured_virtual_desktop_provider_requested: bool,
    backend: Mapping[str, Any],
) -> list[str]:
    blockers = _backend_release_blockers(backend)
    if not configured_virtual_desktop_provider_requested:
        blockers.append("virtual_desktop_provider_not_configured")
    if not blockers:
        blockers.append("virtual_desktop_provider_contract_not_ready")
    return _unique_strings(blockers)


def _backend_release_blockers(backend: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    conformance_ready = backend.get("provider_conformance_public_release_ready")
    if conformance_ready is False:
        blockers.extend(_string_list(backend.get("provider_conformance_release_blocking_conditions")))
        if not blockers:
            blockers.append("virtual_desktop_provider_contract_not_ready")
    elif backend.get("provider_contract_ok") is not True:
        blockers.extend(_string_list(backend.get("provider_contract_blocking_conditions")))
        if not blockers:
            blockers.append("virtual_desktop_provider_contract_not_ready")
    return blockers


def _public_release_next_actions(
    *,
    release_ready: bool,
    isolated_desktop_required: bool,
    run_isolated_provider_smoke: bool,
    configured_virtual_desktop_provider_requested: bool,
    provider_manifest: str,
    blockers: Sequence[str],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    blocker_set = set(blockers)
    if not isolated_desktop_required:
        if release_ready:
            return actions
        return [
            {
                "id": "run_public_release_smoke",
                "title": "Run Direct Desktop release smoke",
                "reason": "The default Direct Desktop runtime path is not release-ready.",
                "command": _public_release_smoke_command(""),
            }
        ]
    if not run_isolated_provider_smoke:
        actions.append(
            {
                "id": "run_isolated_provider_smoke",
                "title": "Run isolated provider smoke",
                "reason": "Public release requires provider runtime evidence.",
                "command": _public_release_smoke_command(
                    provider_manifest,
                    isolated_desktop_required=True,
                ),
            }
        )
    if not configured_virtual_desktop_provider_requested:
        actions.extend(
            [
                {
                    "id": "write_provider_manifest_template",
                    "title": "Create virtual desktop provider manifest",
                    "reason": "No release virtual desktop provider is configured.",
                    "command": (
                        "python scripts/smoke_oha_desktop_agent_release.py "
                        "--write-provider-manifest-template "
                        "tmp/oha-virtual-desktop-provider.manifest.json"
                    ),
                },
                {
                    "id": "provision_virtual_desktop_guest",
                    "title": "Provision the built-in macOS VM guest provider",
                    "reason": (
                        "Oha-Yachiyo includes an authenticated guest agent that runs "
                        "the generic desktop toolset inside a macOS virtual machine."
                    ),
                    "command": (
                        "python scripts/install_virtual_desktop_guest.py "
                        "--ssh-target \"$OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_TARGET\" "
                        "--session-id \"$OHA_YACHIYO_VIRTUAL_DESKTOP_SESSION_ID\" "
                        "--manifest-out tmp/oha-virtual-desktop-provider.manifest.json"
                    ),
                    "required_environment": [
                        "OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_TARGET",
                        "OHA_YACHIYO_VIRTUAL_DESKTOP_SESSION_ID",
                    ],
                },
                {
                    "id": "configure_virtual_desktop_provider",
                    "title": "Configure a real virtual desktop provider",
                    "reason": (
                        "The current loopback provider is for development only and "
                        "cannot prove Hermes/Hanako-style desktop execution."
                    ),
                    "required_environment": [
                        "OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST",
                        "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
                        "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
                    ],
                },
            ]
        )
    if blocker_set & {
        "loopback_desktop_backend",
        "desktop_backend_not_release_ready",
        "real_virtual_desktop_backend_required",
        "virtual_desktop_provider_not_configured",
    }:
        actions.append(
            {
                "id": "attach_real_virtual_desktop_backend",
                "title": "Attach real isolated desktop backend",
                "reason": (
                    "Public release requires a non-loopback desktop backend that "
                    "can open apps, inspect UI, input text, click, and verify state "
                    "without taking over the user's foreground session."
                ),
                "required_contract_fields": {
                    "desktop_session_kind": "virtual_desktop",
                    "desktop_session_isolated": True,
                    "foreground_takeover_required": False,
                    "desktop_backend_is_loopback": False,
                    "desktop_backend_ready_for_public_release": True,
                    "requires_real_virtual_desktop_backend": False,
                },
            }
        )
    if "desktop_provider_missing_required_tools" in blocker_set:
        actions.append(
            {
                "id": "implement_required_provider_tools",
                "title": "Implement required desktop provider tools",
                "reason": "The provider must cover the release desktop-agent tool sequence.",
                "required_tools": list(OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS),
            }
        )
    if provider_manifest:
        actions.append(
            {
                "id": "validate_provider_manifest",
                "title": "Validate provider manifest",
                "reason": "Static manifest validation should pass before runtime smoke.",
                "command": (
                    "python scripts/smoke_oha_desktop_agent_release.py "
                    f"--validate-provider-manifest {provider_manifest}"
                ),
            }
        )
    actions.append(
        {
            "id": "run_public_release_smoke",
            "title": "Run public release smoke",
            "reason": "This is the release gate for desktop-agent provider readiness.",
            "command": _public_release_smoke_command(
                provider_manifest,
                isolated_desktop_required=True,
            ),
        }
    )
    return actions


def _public_release_required_commands(
    provider_manifest: str,
    *,
    isolated_desktop_required: bool,
) -> dict[str, str]:
    if not isolated_desktop_required:
        return {
            "public_release_smoke": _public_release_smoke_command(""),
        }
    manifest = provider_manifest or "tmp/oha-virtual-desktop-provider.manifest.json"
    return {
        "write_manifest_template": (
            "python scripts/smoke_oha_desktop_agent_release.py "
            f"--write-provider-manifest-template {manifest}"
        ),
        "validate_manifest": (
            "python scripts/smoke_oha_desktop_agent_release.py "
            f"--validate-provider-manifest {manifest}"
        ),
        "guest_provider_manifest": (
            "python scripts/run_virtual_desktop_guest_provider.py "
            "--session-id \"$OHA_YACHIYO_VIRTUAL_DESKTOP_SESSION_ID\" --manifest"
        ),
        "install_guest": (
            "python scripts/install_virtual_desktop_guest.py "
            "--ssh-target \"$OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_TARGET\" "
            "--session-id \"$OHA_YACHIYO_VIRTUAL_DESKTOP_SESSION_ID\" "
            f"--manifest-out {manifest}"
        ),
        "ssh_bridge_manifest": (
            "python scripts/run_ssh_virtual_desktop_provider.py "
            "--ssh-target \"$OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_TARGET\" "
            "--remote-provider-executable "
            "\"$OHA_YACHIYO_VIRTUAL_DESKTOP_REMOTE_EXECUTABLE\" "
            "--session-id \"$OHA_YACHIYO_VIRTUAL_DESKTOP_SESSION_ID\" --manifest"
        ),
        "public_release_smoke": _public_release_smoke_command(
            provider_manifest,
            isolated_desktop_required=True,
        ),
    }


def _public_release_smoke_command(
    provider_manifest: str,
    *,
    isolated_desktop_required: bool = False,
) -> str:
    manifest_part = f" --provider-manifest {provider_manifest}" if provider_manifest else ""
    release_flag = (
        "--require-public-release-backend"
        if isolated_desktop_required
        else "--public-release"
    )
    return (
        "python scripts/smoke_oha_desktop_agent_release.py "
        f"{release_flag}{manifest_part} "
        "--report-json tmp/oha-desktop-agent-public-release-smoke.json"
    )


def _clean_provider_manifest(provider_manifest: str | Path | None) -> str:
    return str(provider_manifest or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _unique_strings(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        result.append(item)
        seen.add(item)
    return result
