"""Tests for the loopback headless desktop provider harness."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

from apps.shell.agent.runtime.desktop_execution_providers import (
    desktop_execution_provider_registry_from_env,
    desktop_execution_provider_status_from_env,
)
from apps.shell.agent.runtime.headless_desktop_provider import (
    HeadlessDesktopProvider,
    build_headless_desktop_provider_server,
    main,
)


def test_headless_desktop_provider_status_and_unsupported_tool() -> None:
    provider = HeadlessDesktopProvider(
        provider_id="provider-1",
        supported_tools=["desktop.list_apps"],
    )

    status = provider.status()
    unsupported = provider.execute("desktop.safe_type_text", {"text": "hello"})

    assert status["ok"] is True
    assert status["provider_id"] == "provider-1"
    assert status["foreground_mutation_supported"] is False
    assert status["keyboard_mouse_capture_supported"] is False
    assert status["requires_real_sandbox_for"] == ["click", "type", "shortcut", "focus"]
    assert status["supported_tools"] == ["desktop.list_apps"]
    assert unsupported["ok"] is False
    assert unsupported["error"] == "desktop_provider_tool_unsupported"
    assert unsupported["blocking_conditions"] == ["desktop_provider_tool_unsupported"]
    assert unsupported["supported_tools"] == ["desktop.list_apps"]


def test_headless_desktop_provider_manifest_is_machine_readable(capsys) -> None:
    status_code = main(
        [
            "--manifest",
            "--provider-id",
            "provider-manifest",
            "--tool",
            "desktop.permissions",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert status_code == 0
    assert payload["ok"] is True
    assert payload["provider_id"] == "provider-manifest"
    assert payload["execution_mode"] == "headless_read_only"
    assert payload["foreground_mutation_supported"] is False
    assert payload["keyboard_mouse_capture_supported"] is False
    assert payload["requires_real_sandbox_for"] == ["click", "type", "shortcut", "focus"]
    assert payload["supported_tools"] == ["desktop.permissions"]
    assert payload["endpoints"]["execute"] == "/tools/execute"
    assert payload["environment"]["url"] == "OHA_YACHIYO_DESKTOP_PROVIDER_URL"
    assert payload["entrypoint"]["script"] == "scripts/run_headless_desktop_provider.py"


def test_headless_desktop_provider_executes_safe_tool(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_list_apps(*, query: str = "", limit: Any = 200) -> dict[str, Any]:
        calls.append({"query": query, "limit": limit})
        return {"ok": True, "action": "desktop.list_apps", "data": {"apps": []}}

    monkeypatch.setattr(
        "apps.shell.agent.runtime.headless_desktop_provider.desktop.list_apps",
        fake_list_apps,
    )
    provider = HeadlessDesktopProvider(supported_tools=["desktop.list_apps"])

    result = provider.execute(
        "desktop.list_apps",
        {"query": "Music", "limit": 5},
        approved=True,
        route={"route_id": "route-1"},
        tool_request={"request_id": "request-1"},
    )

    assert result["ok"] is True
    assert result["action"] == "desktop.list_apps"
    assert result["headless_desktop_provider"]["execution_mode"] == "headless_read_only"
    assert result["headless_desktop_provider"]["approved"] is True
    assert result["provider_route"] == {"route_id": "route-1"}
    assert result["provider_request_id"] == "request-1"
    assert calls == [{"query": "Music", "limit": 5}]


def test_headless_desktop_provider_http_status_and_execute(monkeypatch) -> None:
    def fake_list_apps(*, query: str = "", limit: Any = 200) -> dict[str, Any]:
        return {
            "ok": True,
            "action": "desktop.list_apps",
            "summary": f"query={query};limit={limit}",
            "data": {"apps": [{"name": "Music"}]},
        }

    monkeypatch.setattr(
        "apps.shell.agent.runtime.headless_desktop_provider.desktop.list_apps",
        fake_list_apps,
    )
    provider = HeadlessDesktopProvider(
        provider_id="provider-http",
        supported_tools=["desktop.list_apps"],
    )
    server = build_headless_desktop_provider_server(
        host="127.0.0.1",
        port=0,
        token="secret",
        provider=provider,
        quiet=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        status_request = urllib.request.Request(
            f"{base_url}/status",
            headers={"Authorization": "Bearer secret"},
            method="GET",
        )
        with urllib.request.urlopen(status_request, timeout=5) as response:
            status_payload = json.loads(response.read().decode("utf-8"))

        manifest_request = urllib.request.Request(
            f"{base_url}/manifest",
            headers={"Authorization": "Bearer secret"},
            method="GET",
        )
        with urllib.request.urlopen(manifest_request, timeout=5) as response:
            manifest_payload = json.loads(response.read().decode("utf-8"))

        execute_request = urllib.request.Request(
            f"{base_url}/tools/execute",
            data=json.dumps(
                {
                    "tool": "desktop.list_apps",
                    "input": {"query": "Music", "limit": 3},
                    "approved": True,
                }
            ).encode("utf-8"),
            headers={
                "Authorization": "Bearer secret",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(execute_request, timeout=5) as response:
            execute_payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status_payload["ok"] is True
    assert status_payload["provider_id"] == "provider-http"
    assert status_payload["supported_tools"] == ["desktop.list_apps"]
    assert manifest_payload["ok"] is True
    assert manifest_payload["endpoint_urls"]["execute"] == f"{base_url}/tools/execute"
    assert execute_payload["ok"] is True
    assert execute_payload["result"]["ok"] is True
    assert execute_payload["result"]["summary"] == "query=Music;limit=3"
    assert execute_payload["result"]["headless_desktop_provider"]["provider_id"] == (
        "provider-http"
    )


def test_headless_desktop_provider_works_through_runtime_adapter(monkeypatch) -> None:
    def fake_list_apps(*, query: str = "", limit: Any = 200) -> dict[str, Any]:
        return {
            "ok": True,
            "action": "desktop.list_apps",
            "summary": f"query={query};limit={limit}",
            "data": {"apps": [{"name": "Music"}]},
        }

    monkeypatch.setattr(
        "apps.shell.agent.runtime.headless_desktop_provider.desktop.list_apps",
        fake_list_apps,
    )
    provider = HeadlessDesktopProvider(
        provider_id="provider-http",
        supported_tools=["desktop.list_apps"],
    )
    server = build_headless_desktop_provider_server(
        host="127.0.0.1",
        port=0,
        token="secret",
        provider=provider,
        quiet=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {
            "OHA_YACHIYO_DESKTOP_PROVIDER_URL": (
                f"http://127.0.0.1:{server.server_address[1]}"
            ),
            "OHA_YACHIYO_DESKTOP_PROVIDER_ID": "provider-http",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN": "secret",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": "desktop.list_apps",
        }
        status = desktop_execution_provider_status_from_env(env, probe_health=True)
        registry = desktop_execution_provider_registry_from_env(env)
        result = registry.execute_if_routed(
            "desktop.list_apps",
            {"query": "Music", "limit": 4},
            tool_request={
                "tool": "desktop.list_apps",
                "input": {"query": "Music", "limit": 4},
                "desktop_execution_route": {
                    "route_id": "desktop-route:desktop.list_apps",
                    "tool_name": "desktop.list_apps",
                    "requested_mode": "sandbox_preferred",
                    "selected_provider_kind": "sandbox_desktop",
                    "selected_provider_id": "provider-http",
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
                    "provider_id": "provider-http",
                    "status": "available",
                    "supported_tools": ["desktop.list_apps"],
                },
            },
            broker=object(),
            approved=True,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status["available"] is True
    assert status["health"]["checked"] is True
    assert status["health"]["status"] == "ready"
    assert status["health"]["supported_tools"] == ["desktop.list_apps"]
    assert status["keyboard_mouse_capture_supported"] is False
    assert status["requires_real_sandbox_for"] == ["click", "type", "shortcut", "focus"]
    assert result is not None
    assert result["ok"] is True
    assert result["summary"] == "query=Music;limit=4"
    assert result["desktop_execution_provider_routed"] is True
    assert result["desktop_execution_provider"]["provider_id"] == "provider-http"
    assert result["headless_desktop_provider"]["provider_id"] == "provider-http"


def test_desktop_provider_status_reads_backend_release_fields_from_env() -> None:
    status = desktop_execution_provider_status_from_env(
        {
            "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL": (
                "http://127.0.0.1:29093/tools/execute"
            ),
            "OHA_YACHIYO_DESKTOP_PROVIDER_STATUS_URL": (
                "http://127.0.0.1:29093/status"
            ),
            "OHA_YACHIYO_DESKTOP_PROVIDER_ID": "virtual-provider",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": "app.open,desktop.verify",
            "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND": "virtual_desktop",
            "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED": "true",
            "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED": "false",
            "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND": "vnc_virtual_desktop",
            "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK": "false",
            "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE": "true",
            "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND": "false",
        },
        probe_health=False,
    )

    assert status["available"] is True
    assert status["provider_id"] == "virtual-provider"
    assert status["desktop_session_kind"] == "virtual_desktop"
    assert status["desktop_session_isolated"] is True
    assert status["foreground_takeover_required"] is False
    assert status["desktop_backend_kind"] == "vnc_virtual_desktop"
    assert status["desktop_backend_is_loopback"] is False
    assert status["desktop_backend_ready_for_public_release"] is True
    assert status["requires_real_virtual_desktop_backend"] is False


def test_headless_desktop_provider_http_requires_token() -> None:
    server = build_headless_desktop_provider_server(
        host="127.0.0.1",
        port=0,
        token="secret",
        provider=HeadlessDesktopProvider(),
        quiet=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/status",
            method="GET",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            status_code = exc.code
        else:
            raise AssertionError("expected unauthorized response")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status_code == 401
    assert payload == {"error": "unauthorized", "ok": False}
