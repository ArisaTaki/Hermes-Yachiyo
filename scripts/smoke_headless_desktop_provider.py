"""Smoke-test the loopback headless desktop provider through the runtime adapter."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.shell.agent.runtime.desktop_execution_providers import (
    desktop_execution_provider_registry_from_env,
    desktop_execution_provider_status_from_env,
)
from apps.shell.agent.runtime.headless_desktop_provider import (
    HeadlessDesktopProvider,
    build_headless_desktop_provider_server,
)


def main() -> int:
    provider = HeadlessDesktopProvider(
        provider_id="smoke-headless-desktop",
        supported_tools=["desktop.permission_preflight"],
    )
    server = build_headless_desktop_provider_server(
        host="127.0.0.1",
        port=0,
        provider=provider,
        quiet=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        env = {
            "OHA_YACHIYO_DESKTOP_PROVIDER_URL": base_url,
            "OHA_YACHIYO_DESKTOP_PROVIDER_ID": provider.provider_id,
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": "desktop.permission_preflight",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TIMEOUT_SECONDS": "10",
        }
        status = desktop_execution_provider_status_from_env(env, probe_health=True)
        registry = desktop_execution_provider_registry_from_env(env)
        result = registry.execute_if_routed(
            "desktop.permission_preflight",
            {},
            tool_request=_tool_request(provider.provider_id),
            broker=object(),
            approved=True,
        )
        ok = bool(status.get("available")) and isinstance(result, dict) and (
            result.get("ok") is not False
        )
        print(
            json.dumps(
                {
                    "ok": ok,
                    "base_url": base_url,
                    "status": status,
                    "result": result,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if ok else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _tool_request(provider_id: str) -> dict[str, Any]:
    return {
        "tool": "desktop.permission_preflight",
        "input": {},
        "desktop_execution_route": {
            "route_id": "desktop-route:desktop.permission_preflight",
            "tool_name": "desktop.permission_preflight",
            "requested_mode": "sandbox_preferred",
            "selected_provider_kind": "sandbox_desktop",
            "selected_provider_id": provider_id,
            "status": "sandbox_ready",
            "can_execute": True,
            "can_auto_start": True,
            "sandbox_required": True,
            "blocking_conditions": [],
        },
        "sandbox_provider": {
            "available": True,
            "adapter_ready": True,
            "provider_kind": "sandbox_desktop",
            "provider_id": provider_id,
            "status": "available",
            "supported_tools": ["desktop.permission_preflight"],
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
