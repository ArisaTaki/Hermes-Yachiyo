"""Authenticated desktop provider intended to run inside a macOS virtual machine."""

from __future__ import annotations

import argparse
import json
import os
import platform
import stat
import subprocess
import sys
from collections.abc import Iterable, Mapping
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from apps.shell.agent.runtime.controlled_desktop_provider import (
    CONTROLLED_DESKTOP_PROVIDER_TOOLS,
    KEYBOARD_MOUSE_CONTROL_TOOLS,
    ControlledDesktopProvider,
)
from apps.shell.agent.runtime.headless_desktop_provider import (
    build_headless_desktop_provider_server,
)
from apps.shell.yachiyo_agent.desktop_provider_contract import (
    DESKTOP_PROVIDER_CONTRACT_VERSION,
    virtual_desktop_provider_manifest_template,
)
from packages.security import redact_api_error_text

VIRTUAL_DESKTOP_GUEST_PROVIDER_VERSION = "0.1.0"
VIRTUAL_DESKTOP_GUEST_MARKER_SCHEMA = "oha-yachiyo.virtual-desktop-guest.v1"
DEFAULT_PROVIDER_ID = "oha-macos-virtual-desktop"
DEFAULT_PROVIDER_KIND = "sandbox_desktop"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 29097
DEFAULT_BACKEND_KIND = "macos_virtual_machine"
DEFAULT_TOKEN_FILE = Path(
    "~/Library/Application Support/Oha-Yachiyo/desktop-provider.token"
).expanduser()
DEFAULT_GUEST_MARKER = Path(
    "~/Library/Application Support/Oha-Yachiyo/virtual-desktop-guest.json"
).expanduser()

_ATTESTATION_BLOCKERS = {
    "darwin_guest": "virtual_desktop_guest_requires_macos",
    "marker_present": "virtual_desktop_guest_marker_missing",
    "marker_regular_file": "virtual_desktop_guest_marker_invalid",
    "marker_not_symlink": "virtual_desktop_guest_marker_symlink_rejected",
    "marker_owned_by_process_user": "virtual_desktop_guest_marker_owner_mismatch",
    "marker_permissions_restricted": "virtual_desktop_guest_marker_permissions_unsafe",
    "marker_json_valid": "virtual_desktop_guest_marker_json_invalid",
    "marker_schema_current": "virtual_desktop_guest_marker_schema_mismatch",
    "session_id_present": "virtual_desktop_guest_session_id_missing",
    "session_id_matches": "virtual_desktop_guest_session_id_mismatch",
    "boot_session_present": "virtual_desktop_guest_boot_session_missing",
    "boot_session_matches": "virtual_desktop_guest_boot_session_mismatch",
    "hardware_model_present": "virtual_desktop_guest_hardware_model_missing",
    "hardware_model_matches": "virtual_desktop_guest_hardware_model_mismatch",
    "hardware_model_is_virtual": "virtual_desktop_guest_hardware_not_virtual",
    "backend_declared": "virtual_desktop_guest_backend_missing",
    "backend_not_loopback": "virtual_desktop_guest_loopback_backend_rejected",
    "session_isolated": "virtual_desktop_guest_session_not_isolated",
    "foreground_takeover_not_required": "virtual_desktop_guest_foreground_takeover_required",
}
_LOOPBACK_BACKEND_KINDS = {
    "",
    "local_desktop",
    "local_native_desktop",
    "loopback",
    "loopback_session_harness",
    "user_foreground",
}


class VirtualDesktopGuestProvider(ControlledDesktopProvider):
    """Runs generic macOS desktop tools in an attested VM guest session."""

    def __init__(
        self,
        *,
        provider_id: str = DEFAULT_PROVIDER_ID,
        provider_kind: str = DEFAULT_PROVIDER_KIND,
        session_id: str = "",
        marker_path: str | Path = DEFAULT_GUEST_MARKER,
        supported_tools: Iterable[str] | None = None,
    ) -> None:
        super().__init__(
            provider_id=provider_id,
            provider_kind=provider_kind,
            supported_tools=supported_tools or CONTROLLED_DESKTOP_PROVIDER_TOOLS,
            require_approval_for_input=True,
        )
        self.session_id = str(session_id or "").strip()
        self.marker_path = Path(marker_path).expanduser()

    def attestation(self) -> dict[str, Any]:
        return virtual_desktop_guest_attestation(
            marker_path=self.marker_path,
            session_id=self.session_id,
        )

    def status(self) -> dict[str, Any]:
        attestation = self.attestation()
        ready = attestation.get("ok") is True
        backend_kind = str(
            attestation.get("desktop_backend_kind") or DEFAULT_BACKEND_KIND
        ).strip()
        return {
            "ok": ready,
            "status": "ready" if ready else "guest_attestation_failed",
            "version": VIRTUAL_DESKTOP_GUEST_PROVIDER_VERSION,
            "contract_version": DESKTOP_PROVIDER_CONTRACT_VERSION,
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "supported_tools": list(self.supported_tools),
            "capabilities": [
                "desktop_discovery",
                "app_launch",
                "foreground_mutation",
                "foreground_input",
                "keyboard_mouse_capture",
                "sandbox_control",
                "isolated_desktop",
                "virtual_desktop",
                "sandbox_desktop_session",
                "idempotent_tool_requests",
                "permission_diagnostics",
            ],
            "blocking_conditions": list(attestation.get("blocking_conditions") or []),
            "execution_mode": "virtual_desktop",
            "foreground_mutation_supported": True,
            "keyboard_mouse_capture_supported": True,
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": ready,
            "foreground_takeover_required": False if ready else None,
            "desktop_backend_kind": backend_kind,
            "desktop_backend_is_loopback": False if ready else None,
            "desktop_backend_ready_for_public_release": ready,
            "requires_real_virtual_desktop_backend": not ready,
            "virtual_desktop_session_id": self.session_id,
            "guest_attestation": attestation,
            "requires_real_sandbox_for": [],
            "approval_required_tools": sorted(KEYBOARD_MOUSE_CONTROL_TOOLS),
        }

    def manifest(self, *, base_url: str = "") -> dict[str, Any]:
        payload = virtual_desktop_provider_manifest_template(
            provider_id=self.provider_id,
            base_url=base_url or f"http://{DEFAULT_HOST}:{DEFAULT_PORT}",
        )
        payload.update(
            {
                "version": VIRTUAL_DESKTOP_GUEST_PROVIDER_VERSION,
                "contract_version": DESKTOP_PROVIDER_CONTRACT_VERSION,
                "provider_kind": self.provider_kind,
                "supported_tools": list(self.supported_tools),
                "desktop_backend_kind": DEFAULT_BACKEND_KIND,
                "entrypoint": {
                    "script": "scripts/run_virtual_desktop_guest_provider.py",
                    "args": [
                        "--host",
                        DEFAULT_HOST,
                        "--port",
                        str(DEFAULT_PORT),
                        "--provider-id",
                        self.provider_id,
                        "--session-id",
                        self.session_id or "<guest-session-id>",
                        "--guest-marker",
                        str(self.marker_path),
                    ],
                    "cwd": ".",
                },
                "guest_attestation": {
                    "schema_version": VIRTUAL_DESKTOP_GUEST_MARKER_SCHEMA,
                    "marker_path": str(self.marker_path),
                    "requires_current_boot_session": True,
                    "requires_restricted_marker_permissions": True,
                },
            }
        )
        safety = dict(payload.get("safety") or {})
        safety.update(
            {
                "desktop_backend_kind": DEFAULT_BACKEND_KIND,
                "requires_runtime_approval": True,
                "approval_required_tools": sorted(KEYBOARD_MOUSE_CONTROL_TOOLS),
            }
        )
        payload["safety"] = safety
        return payload

    def execute(
        self,
        tool_name: str,
        payload: Mapping[str, Any] | None = None,
        *,
        approved: bool = False,
        route: Mapping[str, Any] | None = None,
        tool_request: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        attestation = self.attestation()
        if attestation.get("ok") is not True:
            return {
                "ok": False,
                "tool": str(tool_name or "").strip(),
                "action": str(tool_name or "").strip(),
                "status": "virtual_desktop_guest_attestation_failed",
                "error": "virtual_desktop_guest_attestation_failed",
                "summary": "Virtual desktop guest attestation failed; tool was not executed.",
                "blocking_conditions": list(
                    attestation.get("blocking_conditions") or []
                ),
                "retryable": False,
                "guest_attestation": attestation,
            }
        return super().execute(
            tool_name,
            payload,
            approved=approved,
            route=route,
            tool_request=tool_request,
        )

    def _with_provider_context(
        self,
        result: dict[str, Any],
        *,
        tool_name: str,
        approved: bool,
        route: Mapping[str, Any] | None,
        tool_request: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        payload = super()._with_provider_context(
            result,
            tool_name=tool_name,
            approved=approved,
            route=route,
            tool_request=tool_request,
        )
        attestation = self.attestation()
        provider_context = {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "version": VIRTUAL_DESKTOP_GUEST_PROVIDER_VERSION,
            "execution_mode": "virtual_desktop",
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "desktop_backend_kind": str(
                attestation.get("desktop_backend_kind") or DEFAULT_BACKEND_KIND
            ),
            "desktop_backend_is_loopback": False,
            "virtual_desktop_session_id": self.session_id,
        }
        payload["virtual_desktop_guest_provider"] = provider_context
        payload["sandbox_provider"] = provider_context
        return payload


def virtual_desktop_guest_attestation(
    *,
    marker_path: str | Path,
    session_id: str,
) -> dict[str, Any]:
    path = Path(marker_path).expanduser()
    clean_session_id = str(session_id or "").strip()
    marker: dict[str, Any] = {}
    marker_json_valid = False
    marker_present = path.exists()
    marker_not_symlink = marker_present and not path.is_symlink()
    marker_regular_file = False
    marker_owned = False
    marker_permissions_restricted = False
    if marker_present and marker_not_symlink:
        try:
            marker_stat = path.stat()
            marker_regular_file = stat.S_ISREG(marker_stat.st_mode)
            marker_owned = marker_stat.st_uid == os.getuid()
            marker_permissions_restricted = marker_stat.st_mode & 0o077 == 0
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                marker = payload
                marker_json_valid = True
        except (OSError, TypeError, ValueError):
            marker_json_valid = False
    current_boot_session = _macos_boot_session_id()
    current_hardware_model = _macos_hardware_model()
    marker_boot_session = str(marker.get("boot_session_id") or "").strip()
    marker_hardware_model = str(marker.get("hardware_model") or "").strip()
    marker_session_id = str(marker.get("session_id") or "").strip()
    backend_kind = str(marker.get("desktop_backend_kind") or "").strip()
    checks = {
        "darwin_guest": platform.system() == "Darwin",
        "marker_present": marker_present,
        "marker_regular_file": marker_regular_file,
        "marker_not_symlink": marker_not_symlink,
        "marker_owned_by_process_user": marker_owned,
        "marker_permissions_restricted": marker_permissions_restricted,
        "marker_json_valid": marker_json_valid,
        "marker_schema_current": (
            str(marker.get("schema_version") or "").strip()
            == VIRTUAL_DESKTOP_GUEST_MARKER_SCHEMA
        ),
        "session_id_present": bool(clean_session_id and marker_session_id),
        "session_id_matches": bool(
            clean_session_id and marker_session_id == clean_session_id
        ),
        "boot_session_present": bool(current_boot_session and marker_boot_session),
        "boot_session_matches": bool(
            current_boot_session and marker_boot_session == current_boot_session
        ),
        "hardware_model_present": bool(
            current_hardware_model and marker_hardware_model
        ),
        "hardware_model_matches": bool(
            current_hardware_model
            and marker_hardware_model == current_hardware_model
        ),
        "hardware_model_is_virtual": _hardware_model_is_virtual(
            current_hardware_model
        ),
        "backend_declared": bool(backend_kind),
        "backend_not_loopback": (
            backend_kind.lower().replace("-", "_") not in _LOOPBACK_BACKEND_KINDS
        ),
        "session_isolated": marker.get("desktop_session_isolated") is True,
        "foreground_takeover_not_required": (
            marker.get("foreground_takeover_required") is False
        ),
    }
    blocking_conditions = [
        _ATTESTATION_BLOCKERS[key]
        for key, passed in checks.items()
        if not passed
    ]
    return {
        "ok": all(checks.values()),
        "schema_version": VIRTUAL_DESKTOP_GUEST_MARKER_SCHEMA,
        "marker_path": str(path),
        "session_id": clean_session_id,
        "boot_session_id": current_boot_session,
        "hardware_model": current_hardware_model,
        "desktop_backend_kind": backend_kind,
        "checks": checks,
        "blocking_conditions": blocking_conditions,
    }


def virtual_desktop_guest_marker_template(
    *,
    session_id: str,
    backend_kind: str = DEFAULT_BACKEND_KIND,
) -> dict[str, Any]:
    return {
        "schema_version": VIRTUAL_DESKTOP_GUEST_MARKER_SCHEMA,
        "session_id": str(session_id or "").strip(),
        "boot_session_id": _macos_boot_session_id(),
        "hardware_model": _macos_hardware_model(),
        "desktop_backend_kind": str(backend_kind or DEFAULT_BACKEND_KIND).strip(),
        "desktop_session_isolated": True,
        "foreground_takeover_required": False,
    }


def build_virtual_desktop_guest_provider_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: str,
    provider: VirtualDesktopGuestProvider,
    quiet: bool = False,
) -> ThreadingHTTPServer:
    if not str(token or "").strip():
        raise ValueError("virtual desktop guest provider requires a bearer token")
    return build_headless_desktop_provider_server(
        host=host,
        port=port,
        token=token,
        provider=provider,
        quiet=quiet,
    )


def serve_virtual_desktop_guest_provider(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: str,
    provider: VirtualDesktopGuestProvider,
    quiet: bool = False,
) -> None:
    status = provider.status()
    if status.get("ok") is not True:
        blockers = ",".join(status.get("blocking_conditions") or [])
        raise RuntimeError(f"virtual desktop guest attestation failed: {blockers}")
    server = build_virtual_desktop_guest_provider_server(
        host=host,
        port=port,
        token=token,
        provider=provider,
        quiet=quiet,
    )
    actual_host, actual_port = server.server_address
    base_url = f"http://{actual_host}:{actual_port}"
    print(
        json.dumps(
            {
                **status,
                "authentication_configured": True,
                "url": base_url,
                "status_url": f"{base_url}/status",
                "execute_url": f"{base_url}/tools/execute",
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    provider = VirtualDesktopGuestProvider(
        provider_id=args.provider_id,
        provider_kind=args.provider_kind,
        session_id=args.session_id,
        marker_path=args.guest_marker,
        supported_tools=args.tool,
    )
    if args.manifest:
        print(json.dumps(provider.manifest(), ensure_ascii=False, sort_keys=True))
        return 0
    if args.write_guest_marker:
        boot_session_id = _macos_boot_session_id()
        hardware_model = _macos_hardware_model()
        backend_kind = str(args.backend_kind or "").strip()
        marker_blockers = []
        if platform.system() != "Darwin":
            marker_blockers.append("virtual_desktop_guest_requires_macos")
        if not boot_session_id:
            marker_blockers.append("virtual_desktop_guest_boot_session_missing")
        if not _hardware_model_is_virtual(hardware_model):
            marker_blockers.append("virtual_desktop_guest_hardware_not_virtual")
        if backend_kind.lower().replace("-", "_") in _LOOPBACK_BACKEND_KINDS:
            marker_blockers.append("virtual_desktop_guest_loopback_backend_rejected")
        if marker_blockers:
            print(
                json.dumps(
                    {"ok": False, "blocking_conditions": marker_blockers},
                    sort_keys=True,
                )
            )
            return 2
        marker_path = Path(args.write_guest_marker).expanduser()
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(
            json.dumps(
                virtual_desktop_guest_marker_template(
                    session_id=args.session_id,
                    backend_kind=backend_kind,
                ),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        marker_path.chmod(0o600)
        print(json.dumps({"ok": True, "marker_path": str(marker_path)}))
        return 0
    try:
        token = _desktop_provider_token(
            direct_token=(
                args.token or os.getenv("OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN", "")
            ),
            token_file=(
                args.token_file
                or os.getenv("OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN_FILE", "")
            ),
        )
        serve_virtual_desktop_guest_provider(
            host=args.host,
            port=args.port,
            token=token,
            provider=provider,
            quiet=args.quiet,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": redact_api_error_text(exc),
                    "blocking_conditions": provider.status().get(
                        "blocking_conditions", []
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        return 2
    return 0


def _macos_boot_session_id() -> str:
    if platform.system() != "Darwin":
        return ""
    try:
        process = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return str(process.stdout or "").strip() if process.returncode == 0 else ""


def _macos_hardware_model() -> str:
    if platform.system() != "Darwin":
        return ""
    try:
        process = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "hw.model"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return str(process.stdout or "").strip() if process.returncode == 0 else ""


def _hardware_model_is_virtual(value: str) -> bool:
    return "virtual" in str(value or "").strip().lower()


def _desktop_provider_token(
    *,
    direct_token: str,
    token_file: str | Path | None,
) -> str:
    token = str(direct_token or "").strip()
    if token:
        return token
    raw_path = str(token_file or "").strip()
    if not raw_path:
        return ""
    path = Path(raw_path).expanduser()
    if path.is_symlink():
        raise ValueError("desktop provider token file must not be a symlink")
    token_stat = path.stat()
    if not stat.S_ISREG(token_stat.st_mode):
        raise ValueError("desktop provider token file must be a regular file")
    if token_stat.st_uid != os.getuid():
        raise ValueError("desktop provider token file owner mismatch")
    if token_stat.st_mode & 0o077:
        raise ValueError("desktop provider token file permissions must be 0600")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("desktop provider token file is empty")
    if len(token) > 4096:
        raise ValueError("desktop provider token file is too large")
    return token


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--token", default="")
    parser.add_argument("--token-file", default="")
    parser.add_argument("--provider-id", default=DEFAULT_PROVIDER_ID)
    parser.add_argument("--provider-kind", default=DEFAULT_PROVIDER_KIND)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--guest-marker", default=str(DEFAULT_GUEST_MARKER))
    parser.add_argument("--backend-kind", default=DEFAULT_BACKEND_KIND)
    parser.add_argument("--tool", action="append", default=[])
    parser.add_argument("--manifest", action="store_true")
    parser.add_argument("--write-guest-marker", default="")
    parser.add_argument("--quiet", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
