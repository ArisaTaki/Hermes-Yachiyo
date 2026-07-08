#!/usr/bin/env python3
"""Smoke-test the isolated desktop provider through the runtime adapter."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

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
from apps.shell.yachiyo_agent.isolated_provider_session import (
    start_isolated_desktop_provider_session,
    stop_isolated_desktop_provider_session,
)
from apps.shell.yachiyo_agent.desktop_provider_contract import (
    OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    virtual_desktop_provider_contract_evidence,
)

SMOKE_TOOLS = OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS
SMOKE_APP_NAME = "Apple Music"
SMOKE_TEXT = "morning playlist"
_PROVIDER_START_COMMAND_ENV = "OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND"


def run_smoke(*, use_configured_provider: bool = False) -> dict[str, Any]:
    if use_configured_provider:
        return _run_configured_provider_smoke()

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
        return _run_provider_smoke(
            registry=registry,
            provider_id=provider.provider_id,
            status=status,
            base_url=base_url,
            use_configured_provider=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _run_configured_provider_smoke() -> dict[str, Any]:
    status = desktop_execution_provider_status_from_env(probe_health=True)
    managed_session: dict[str, Any] = {}
    stop_managed_session = False
    if _configured_provider_needs_start(status) and _managed_provider_start_configured():
        try:
            managed_session = start_isolated_desktop_provider_session(
                {"tools": list(SMOKE_TOOLS)}
            )
            stop_managed_session = bool(managed_session.get("started"))
            status = desktop_execution_provider_status_from_env(probe_health=True)
        except Exception as exc:
            return _provider_status_only_report(
                status,
                reason="managed_external_provider_start_failed",
                use_configured_provider=True,
                managed_provider_session={"ok": False, "error": str(exc)},
            )
    provider_id = str(status.get("provider_id") or "").strip()
    base_url = str(status.get("endpoint_origin") or "").strip()
    if status.get("configured") is not True:
        return _provider_status_only_report(
            status,
            reason="desktop_execution_provider_not_configured",
            use_configured_provider=True,
            managed_provider_session=managed_session,
        )
    if not provider_id:
        return _provider_status_only_report(
            status,
            reason="desktop_execution_provider_missing_provider_id",
            use_configured_provider=True,
            managed_provider_session=managed_session,
        )
    registry = desktop_execution_provider_registry_from_env()
    try:
        report = _run_provider_smoke(
            registry=registry,
            provider_id=provider_id,
            status=status,
            base_url=base_url,
            use_configured_provider=True,
        )
        report["managed_provider_session"] = dict(managed_session)
        report["managed_provider_started"] = bool(managed_session.get("started"))
        return report
    finally:
        if stop_managed_session:
            stop_isolated_desktop_provider_session()


def _configured_provider_needs_start(status: Mapping[str, Any]) -> bool:
    if status.get("configured") is not True:
        return True
    return not (bool(status.get("available")) and bool(status.get("adapter_ready")))


def _managed_provider_start_configured() -> bool:
    return bool(str(os.environ.get(_PROVIDER_START_COMMAND_ENV) or "").strip())


def _run_provider_smoke(
    *,
    registry: Any,
    provider_id: str,
    status: Mapping[str, Any],
    base_url: str,
    use_configured_provider: bool,
) -> dict[str, Any]:
    status_payload = dict(status)
    tool_results = [
        _execute_tool(
            registry,
            provider_id,
            "desktop.list_apps",
            {"query": SMOKE_APP_NAME, "limit": 20},
            provider_status=status_payload,
        ),
        _execute_tool(
            registry,
            provider_id,
            "app.open",
            {
                "app_name": "<selected app from desktop.list_apps>",
                "selection_source": "desktop.list_apps",
                "query": SMOKE_APP_NAME,
            },
            provider_status=status_payload,
        ),
        _execute_tool(
            registry,
            provider_id,
            "desktop.inspect_app",
            {
                "app_name": SMOKE_APP_NAME,
                "open_if_needed": False,
                "focus": True,
                "limit": 20,
            },
            provider_status=status_payload,
        ),
        _execute_tool(
            registry,
            provider_id,
            "media.music_app_open_and_play",
            {"app_name": SMOKE_APP_NAME},
            provider_status=status_payload,
        ),
        _execute_tool(
            registry,
            provider_id,
            "media.music_app_control",
            {"app_name": SMOKE_APP_NAME, "action": "pause"},
            provider_status=status_payload,
        ),
        _execute_tool(
            registry,
            provider_id,
            "desktop.read_ui",
            {"app_name": SMOKE_APP_NAME},
            provider_status=status_payload,
        ),
        _execute_tool(
            registry,
            provider_id,
            "desktop.click_ui_element",
            {
                "target": "Search",
                "role_filter": "text_field",
                "expected_app_name": SMOKE_APP_NAME,
            },
            provider_status=status_payload,
        ),
        _execute_tool(
            registry,
            provider_id,
            "desktop.safe_type_text",
            {"text": SMOKE_TEXT},
            provider_status=status_payload,
        ),
        _execute_tool(
            registry,
            provider_id,
            "desktop.safe_shortcut",
            {"action": "submit"},
            provider_status=status_payload,
        ),
        _execute_tool(
            registry,
            provider_id,
            "desktop.verify",
            {
                "app_name": SMOKE_APP_NAME,
                "target": "Search",
                "expected_text": SMOKE_TEXT,
            },
            provider_status=status_payload,
        ),
    ]
    result = tool_results[-1] if tool_results else {}
    result_by_tool = {
        str(item.get("tool") or item.get("action") or ""): item
        for item in tool_results
        if isinstance(item, dict)
    }
    checks = _provider_smoke_checks(
        status_payload,
        tool_results,
        result_by_tool,
        use_configured_provider=use_configured_provider,
    )
    provider_contract = virtual_desktop_provider_contract_evidence(
        status_payload,
        required_tools=SMOKE_TOOLS,
        tool_results=tool_results if use_configured_provider else None,
    )
    if use_configured_provider:
        checks["provider_contract_ready"] = provider_contract["ok"] is True
    return {
        "ok": all(checks.values()),
        "mode": "isolated_desktop_provider_smoke",
        "base_url": base_url,
        "use_configured_provider": bool(use_configured_provider),
        "status": status_payload,
        "result": result,
        "tool_results": tool_results,
        "tool_sequence": list(SMOKE_TOOLS),
        "checks": checks,
        "provider_contract": provider_contract,
        **_provider_status_summary(status_payload),
        "covered_tools": list(SMOKE_TOOLS),
    }


def _provider_smoke_checks(
    status: Mapping[str, Any],
    tool_results: Sequence[dict[str, Any]],
    result_by_tool: Mapping[str, dict[str, Any]],
    *,
    use_configured_provider: bool,
) -> dict[str, bool]:
    verify_data = result_by_tool.get("desktop.verify", {}).get("data", {})
    common = {
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
            isinstance(item, dict) and _tool_result_reports_isolated_session(item)
            for item in tool_results
        ),
        "tool_sequence_completed": [
            item.get("action") for item in tool_results if isinstance(item, dict)
        ]
        == list(SMOKE_TOOLS),
    }
    if use_configured_provider:
        return {
            **common,
            "provider_backend_ready_for_public_release": (
                status.get("desktop_backend_ready_for_public_release") is True
            ),
            "provider_backend_not_loopback": (
                status.get("desktop_backend_is_loopback") is not True
            ),
            "verify_tool_completed": result_by_tool.get("desktop.verify", {}).get("ok")
            is not False,
        }
    read_ui_elements = (
        result_by_tool.get("desktop.read_ui", {}).get("data", {}).get("elements", [])
    )
    inspect_data = result_by_tool.get("desktop.inspect_app", {}).get("data", {})
    discovered_apps = (
        result_by_tool.get("desktop.list_apps", {}).get("data", {}).get("matches", [])
    )
    return {
        **common,
        "provider_backend_identifies_loopback_harness": (
            status.get("desktop_backend_kind") == "loopback_session_harness"
            and status.get("desktop_backend_is_loopback") is True
        ),
        "provider_backend_marks_real_virtual_desktop_needed": (
            status.get("desktop_backend_ready_for_public_release") is False
            and status.get("requires_real_virtual_desktop_backend") is True
        ),
        "app_discovery_recorded": (
            isinstance(discovered_apps, list)
            and any(
                item.get("app_name") == SMOKE_APP_NAME
                and item.get("isolated_discovery") is True
                for item in discovered_apps
                if isinstance(item, dict)
            )
        ),
        "open_app_recorded": (
            result_by_tool.get("app.open", {}).get("data", {}).get("app_name")
            == SMOKE_APP_NAME
        ),
        "inspect_app_ready": (
            inspect_data.get("app_name") == SMOKE_APP_NAME
            and inspect_data.get("running") is True
            and inspect_data.get("ready_for_foreground_action") is True
            and inspect_data.get("ui_element_count", 0) > 0
        ),
        "media_open_recorded": (
            result_by_tool.get("media.music_app_open_and_play", {})
            .get("data", {})
            .get("isolated_playback_state")
            == "playing"
            and result_by_tool.get("media.music_app_open_and_play", {})
            .get("data", {})
            .get("real_desktop_mutated")
            is False
        ),
        "media_control_recorded": (
            result_by_tool.get("media.music_app_control", {})
            .get("data", {})
            .get("isolated_playback_state")
            == "paused"
            and result_by_tool.get("media.music_app_control", {})
            .get("data", {})
            .get("real_desktop_mutated")
            is False
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


def _tool_result_reports_isolated_session(item: Mapping[str, Any]) -> bool:
    isolated_provider = item.get("isolated_desktop_provider")
    if (
        isinstance(isolated_provider, Mapping)
        and isolated_provider.get("desktop_session_isolated") is True
    ):
        return True
    sandbox_provider = item.get("sandbox_provider")
    return (
        isinstance(sandbox_provider, Mapping)
        and sandbox_provider.get("desktop_session_isolated") is True
    )


def _provider_status_only_report(
    status: Mapping[str, Any],
    *,
    reason: str,
    use_configured_provider: bool,
    managed_provider_session: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    status_payload = dict(status)
    session_payload = dict(managed_provider_session or {})
    checks = {
        "provider_configured": status_payload.get("configured") is True,
        "provider_available": bool(status_payload.get("available")),
        "provider_session_isolated": bool(
            status_payload.get("desktop_session_isolated")
        ),
        "foreground_takeover_not_required": (
            status_payload.get("foreground_takeover_required") is False
        ),
        "provider_backend_ready_for_public_release": (
            status_payload.get("desktop_backend_ready_for_public_release") is True
        ),
    }
    provider_contract = virtual_desktop_provider_contract_evidence(
        status_payload,
        required_tools=SMOKE_TOOLS,
        tool_results=[],
    )
    return {
        "ok": False,
        "mode": "isolated_desktop_provider_smoke",
        "use_configured_provider": bool(use_configured_provider),
        "status": status_payload,
        "result": {},
        "tool_results": [],
        "tool_sequence": list(SMOKE_TOOLS),
        "checks": checks,
        "reason": reason,
        "provider_contract": provider_contract,
        "managed_provider_session": session_payload,
        "managed_provider_started": bool(session_payload.get("started")),
        **_provider_status_summary(status_payload),
        "covered_tools": [],
    }


def _provider_status_summary(status: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "desktop_session_kind": str(status.get("desktop_session_kind") or ""),
        "desktop_session_isolated": status.get("desktop_session_isolated"),
        "foreground_takeover_required": status.get("foreground_takeover_required"),
        "keyboard_mouse_capture_supported": status.get(
            "keyboard_mouse_capture_supported"
        ),
        "desktop_backend_kind": status.get("desktop_backend_kind"),
        "desktop_backend_is_loopback": status.get("desktop_backend_is_loopback"),
        "desktop_backend_ready_for_public_release": status.get(
            "desktop_backend_ready_for_public_release"
        ),
        "requires_real_virtual_desktop_backend": status.get(
            "requires_real_virtual_desktop_backend"
        ),
        "supported_tools": status.get("supported_tools") or [],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--use-configured-provider",
        action="store_true",
        help=(
            "Use OHA_YACHIYO_DESKTOP_PROVIDER_* from the environment instead of "
            "starting the local loopback harness."
        ),
    )
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
    evidence = run_smoke(use_configured_provider=bool(args.use_configured_provider))
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("ok") is True else 1


def _execute_tool(
    registry: Any,
    provider_id: str,
    tool_name: str,
    payload: dict[str, Any],
    *,
    provider_status: Mapping[str, Any],
) -> dict[str, Any]:
    result = registry.execute_if_routed(
        tool_name,
        payload,
        tool_request=_tool_request(
            provider_id,
            tool_name,
            payload,
            provider_status=provider_status,
        ),
        broker=object(),
        approved=True,
    )
    return dict(result) if isinstance(result, dict) else {"ok": False}


def _tool_request(
    provider_id: str,
    tool_name: str,
    payload: dict[str, Any],
    *,
    provider_status: Mapping[str, Any],
) -> dict[str, Any]:
    supported_tools = provider_status.get("supported_tools")
    if not isinstance(supported_tools, list):
        supported_tools = list(SMOKE_TOOLS)
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
            "status": str(provider_status.get("status") or "available"),
            "supported_tools": supported_tools,
            "keyboard_mouse_capture_supported": provider_status.get(
                "keyboard_mouse_capture_supported",
                True,
            ),
            "desktop_session_kind": str(
                provider_status.get("desktop_session_kind") or "isolated_desktop"
            ),
            "desktop_session_isolated": provider_status.get(
                "desktop_session_isolated",
                True,
            ),
            "foreground_takeover_required": provider_status.get(
                "foreground_takeover_required",
                False,
            ),
            "desktop_backend_kind": str(
                provider_status.get("desktop_backend_kind") or ""
            ),
            "desktop_backend_is_loopback": provider_status.get(
                "desktop_backend_is_loopback"
            ),
            "desktop_backend_ready_for_public_release": provider_status.get(
                "desktop_backend_ready_for_public_release"
            ),
            "requires_real_virtual_desktop_backend": provider_status.get(
                "requires_real_virtual_desktop_backend"
            ),
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
