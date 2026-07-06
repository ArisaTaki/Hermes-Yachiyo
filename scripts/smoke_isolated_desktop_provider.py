#!/usr/bin/env python3
"""Smoke-test the isolated desktop provider through the runtime adapter."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.shell.agent.runtime.desktop_execution_providers import (
    desktop_execution_provider_registry_from_env,
    desktop_execution_provider_status_from_env,
)
from apps.shell.agent.runtime.isolated_desktop_provider import (
    IsolatedDesktopProvider,
    build_isolated_desktop_provider_server,
)

SMOKE_TOOLS = (
    "desktop.open_app",
    "desktop.read_ui",
    "desktop.click_ui_element",
    "desktop.safe_type_text",
    "desktop.safe_shortcut",
    "desktop.verify",
)
SMOKE_APP_NAME = "Apple Music"
SMOKE_TEXT = "morning playlist"


def run_smoke() -> dict[str, Any]:
    provider = IsolatedDesktopProvider(
        provider_id="smoke-isolated-desktop",
        supported_tools=SMOKE_TOOLS,
    )
    server = build_isolated_desktop_provider_server(
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
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": ",".join(SMOKE_TOOLS),
            "OHA_YACHIYO_DESKTOP_PROVIDER_TIMEOUT_SECONDS": "10",
        }
        status = desktop_execution_provider_status_from_env(env, probe_health=True)
        registry = desktop_execution_provider_registry_from_env(env)
        tool_results = [
            _execute_tool(
                registry,
                provider.provider_id,
                "desktop.open_app",
                {"app_name": SMOKE_APP_NAME},
            ),
            _execute_tool(
                registry,
                provider.provider_id,
                "desktop.read_ui",
                {"app_name": SMOKE_APP_NAME},
            ),
            _execute_tool(
                registry,
                provider.provider_id,
                "desktop.click_ui_element",
                {
                    "target": "Search",
                    "role_filter": "text_field",
                    "expected_app_name": SMOKE_APP_NAME,
                },
            ),
            _execute_tool(
                registry,
                provider.provider_id,
                "desktop.safe_type_text",
                {"text": SMOKE_TEXT},
            ),
            _execute_tool(
                registry,
                provider.provider_id,
                "desktop.safe_shortcut",
                {"action": "submit"},
            ),
            _execute_tool(
                registry,
                provider.provider_id,
                "desktop.verify",
                {
                    "app_name": SMOKE_APP_NAME,
                    "target": "Search",
                    "expected_text": SMOKE_TEXT,
                },
            ),
        ]
        result = tool_results[-1] if tool_results else {}
        result_by_tool = {
            str(item.get("tool") or item.get("action") or ""): item
            for item in tool_results
            if isinstance(item, dict)
        }
        read_ui_elements = (
            result_by_tool.get("desktop.read_ui", {})
            .get("data", {})
            .get("elements", [])
        )
        verify_data = result_by_tool.get("desktop.verify", {}).get("data", {})
        checks = {
            "provider_available": bool(status.get("available")),
            "provider_session_isolated": bool(status.get("desktop_session_isolated")),
            "foreground_takeover_not_required": (
                status.get("foreground_takeover_required") is False
            ),
            "all_tools_routed": all(
                isinstance(item, dict)
                and item.get("desktop_execution_provider_routed") is True
                for item in tool_results
            ),
            "all_tool_results_ok": all(
                isinstance(item, dict) and item.get("ok") is not False
                for item in tool_results
            ),
            "all_tool_results_isolated": all(
                isinstance(item, dict)
                and item.get("isolated_desktop_provider", {}).get(
                    "desktop_session_isolated"
                )
                is True
                for item in tool_results
            ),
            "tool_sequence_completed": [
                item.get("action") for item in tool_results if isinstance(item, dict)
            ]
            == list(SMOKE_TOOLS),
            "open_app_recorded": (
                result_by_tool.get("desktop.open_app", {})
                .get("data", {})
                .get("app_name")
                == SMOKE_APP_NAME
            ),
            "read_ui_returned_elements": isinstance(read_ui_elements, list)
            and bool(read_ui_elements),
            "click_target_recorded": (
                result_by_tool.get("desktop.click_ui_element", {})
                .get("data", {})
                .get("isolated_event", {})
                .get("target")
                == "Search"
            ),
            "type_text_recorded": (
                result_by_tool.get("desktop.safe_type_text", {})
                .get("data", {})
                .get("isolated_event", {})
                .get("text_buffer")
                == SMOKE_TEXT
            ),
            "verify_expected_text": verify_data.get("expected_text_found") is True,
            "verify_target_focused": verify_data.get("expected_target_focused") is True,
        }
        ok = all(checks.values())
        return {
            "ok": ok,
            "mode": "isolated_desktop_provider_smoke",
            "base_url": base_url,
            "status": status,
            "result": result,
            "tool_results": tool_results,
            "tool_sequence": list(SMOKE_TOOLS),
            "checks": checks,
            "desktop_session_kind": str(status.get("desktop_session_kind") or ""),
            "desktop_session_isolated": status.get("desktop_session_isolated"),
            "foreground_takeover_required": status.get("foreground_takeover_required"),
            "keyboard_mouse_capture_supported": status.get(
                "keyboard_mouse_capture_supported"
            ),
            "supported_tools": status.get("supported_tools") or [],
            "covered_tools": list(SMOKE_TOOLS),
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional JSON evidence report path.",
    )
    return parser


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = run_smoke()
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("ok") is True else 1


def _execute_tool(
    registry: Any,
    provider_id: str,
    tool_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    result = registry.execute_if_routed(
        tool_name,
        payload,
        tool_request=_tool_request(provider_id, tool_name, payload),
        broker=object(),
        approved=True,
    )
    return dict(result) if isinstance(result, dict) else {"ok": False}


def _tool_request(
    provider_id: str,
    tool_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "tool": tool_name,
        "input": dict(payload),
        "desktop_execution_route": {
            "route_id": f"desktop-route:{tool_name}",
            "tool_name": tool_name,
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
            "supported_tools": list(SMOKE_TOOLS),
            "keyboard_mouse_capture_supported": True,
            "desktop_session_kind": "isolated_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
