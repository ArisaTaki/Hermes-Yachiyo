"""Tests for desktop execution provider adapters."""

from __future__ import annotations

import json
from typing import Any

from apps.shell.agent.runtime.desktop_execution_providers import (
    LOCAL_DESKTOP_PROVIDER_ID,
    LOCAL_DESKTOP_PROVIDER_KIND,
    desktop_execution_provider_status_from_env,
    desktop_execution_provider_registry_from_env,
)
from apps.shell.yachiyo_agent.desktop_execution_policy import (
    desktop_execution_route_decision,
    sandbox_desktop_provider_status,
)


class FakeResponse:
    def __init__(self, payload: dict[str, Any], *, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def getcode(self) -> int:
        return self.status


def _sandbox_tool_request() -> dict[str, Any]:
    return {
        "tool": "desktop.safe_type_text",
        "input": {"text": "hello"},
        "desktop_execution_route": {
            "route_id": "desktop-route:desktop.safe_type_text",
            "tool_name": "desktop.safe_type_text",
            "requested_mode": "sandbox_preferred",
            "selected_provider_kind": "sandbox_desktop",
            "selected_provider_id": "sandbox-1",
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
            "provider_id": "sandbox-1",
            "status": "available",
            "supported_tools": ["desktop.safe_type_text"],
        },
    }


def _local_tool_request(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool": tool_name,
        "input": payload,
        "desktop_execution_route": {
            "route_id": f"desktop-route:{tool_name}",
            "tool_name": tool_name,
            "requested_mode": "preview_input",
            "selected_provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
            "selected_provider_id": LOCAL_DESKTOP_PROVIDER_ID,
            "status": "sandbox_ready",
            "can_execute": True,
            "can_auto_start": True,
            "sandbox_required": True,
            "blocking_conditions": [],
        },
        "sandbox_provider": {
            "available": True,
            "adapter_ready": True,
            "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
            "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
            "status": "available",
            "supported_tools": [tool_name],
        },
    }


def test_desktop_provider_registry_from_env_routes_tool_to_local_http_provider() -> None:
    requests: list[dict[str, Any]] = []

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        requests.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "timeout": timeout,
                "payload": json.loads(request.data.decode("utf-8")),
            }
        )
        return FakeResponse({"result": {"ok": True, "data": {"typed": True}}})

    registry = desktop_execution_provider_registry_from_env(
        {
            "OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://127.0.0.1:19091",
            "OHA_YACHIYO_DESKTOP_PROVIDER_ID": "sandbox-1",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN": "secret-token",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": "desktop.safe_type_text",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TIMEOUT_SECONDS": "3.5",
        },
        urlopen=fake_urlopen,
    )
    tool_request = _sandbox_tool_request()

    result = registry.execute_if_routed(
        "desktop.safe_type_text",
        {"text": "hello"},
        tool_request=tool_request,
        broker=object(),
        approved=True,
    )

    assert result is not None
    assert result["ok"] is True
    assert result["desktop_execution_provider_routed"] is True
    assert result["desktop_execution_provider"]["provider_id"] == "sandbox-1"
    assert result["desktop_execution_provider"]["adapter_registered"] is True
    assert result["desktop_execution_provider_transport"]["endpoint_path"] == "/tools/execute"
    assert requests[0]["url"] == "http://127.0.0.1:19091/tools/execute"
    assert requests[0]["headers"]["Authorization"] == "Bearer secret-token"
    assert requests[0]["timeout"] == 3.5
    assert requests[0]["payload"]["tool"] == "desktop.safe_type_text"
    assert requests[0]["payload"]["approved"] is True
    assert requests[0]["payload"]["provider"]["provider_id"] == "sandbox-1"


def test_default_desktop_provider_registry_routes_low_risk_tools_to_local_broker() -> None:
    calls: list[tuple[str, dict[str, Any], bool]] = []

    class FakeBroker:
        def call(
            self,
            name: str,
            payload: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            calls.append((name, payload, approved))
            return {
                "ok": True,
                "action": name,
                "data": {"app_name": payload.get("app_name")},
            }

    registry = desktop_execution_provider_registry_from_env({})
    tool_request = _local_tool_request("app.open", {"app_name": "Music"})

    result = registry.execute_if_routed(
        "app.open",
        {"app_name": "Music"},
        tool_request=tool_request,
        broker=FakeBroker(),
    )

    assert result is not None
    assert result["ok"] is True
    assert result["desktop_execution_provider_routed"] is True
    assert result["desktop_execution_provider"]["provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert result["desktop_execution_provider"]["provider_id"] == LOCAL_DESKTOP_PROVIDER_ID
    assert result["local_desktop_provider"]["provider_id"] == LOCAL_DESKTOP_PROVIDER_ID
    assert calls == [("app.open", {"app_name": "Music"}, False)]


def test_desktop_provider_status_from_env_reports_unchecked_local_provider() -> None:
    status = desktop_execution_provider_status_from_env(
        {
            "OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://127.0.0.1:19091",
            "OHA_YACHIYO_DESKTOP_PROVIDER_ID": "sandbox-1",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": "desktop.safe_type_text,desktop.click",
        }
    )

    assert status["configured"] is True
    assert status["available"] is True
    assert status["adapter_ready"] is True
    assert status["provider_kind"] == "sandbox_desktop"
    assert status["provider_id"] == "sandbox-1"
    assert status["status"] == "available"
    assert status["supported_tools"] == ["desktop.safe_type_text", "desktop.click"]
    assert status["health"]["checked"] is False
    assert status["health"]["status"] == "not_checked"
    assert status["health"]["endpoint_path"] == "/status"


def test_desktop_provider_status_from_env_probes_health_endpoint() -> None:
    requests: list[dict[str, Any]] = []

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        requests.append(
            {
                "method": request.get_method(),
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "timeout": timeout,
            }
        )
        return FakeResponse(
            {
                "ok": True,
                "status": "ready",
                "version": "0.1.0",
                "supported_tools": ["desktop.safe_type_text"],
                "capabilities": ["keyboard_mouse_capture"],
            }
        )

    status = desktop_execution_provider_status_from_env(
        {
            "OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://localhost:19091",
            "OHA_YACHIYO_DESKTOP_PROVIDER_ID": "sandbox-1",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN": "secret-token",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TIMEOUT_SECONDS": "2",
        },
        probe_health=True,
        urlopen=fake_urlopen,
    )

    assert status["available"] is True
    assert status["adapter_ready"] is True
    assert status["status"] == "available"
    assert status["health"]["ok"] is True
    assert status["health"]["checked"] is True
    assert status["health"]["status"] == "ready"
    assert status["health"]["provider_version"] == "0.1.0"
    assert status["health"]["supported_tools"] == ["desktop.safe_type_text"]
    assert status["health"]["capabilities"] == ["keyboard_mouse_capture"]
    assert requests == [
        {
            "method": "GET",
            "url": "http://localhost:19091/status",
            "headers": {
                "Accept": "application/json",
                "Authorization": "Bearer secret-token",
                "Content-type": "application/json",
                "User-agent": "Oha-Yachiyo-Desktop-Provider/1",
            },
            "timeout": 2.0,
        }
    ]


def test_desktop_provider_registry_from_env_ignores_remote_url_by_default() -> None:
    registry = desktop_execution_provider_registry_from_env(
        {"OHA_YACHIYO_DESKTOP_PROVIDER_URL": "https://example.com/provider"}
    )
    result = registry.execute_if_routed(
        "desktop.safe_type_text",
        {"text": "hello"},
        tool_request=_sandbox_tool_request(),
        broker=object(),
    )

    assert result is not None
    assert result["ok"] is False
    assert result["error"] == "desktop_execution_provider_unavailable"

    status = desktop_execution_provider_status_from_env(
        {"OHA_YACHIYO_DESKTOP_PROVIDER_URL": "https://example.com/provider"}
    )
    assert status["available"] is False
    assert status["status"] == "remote_provider_blocked"
    assert status["blocking_conditions"] == ["desktop_execution_provider_remote_blocked"]


def test_desktop_provider_transport_failure_stays_structured() -> None:
    def fake_urlopen(_request: Any, *, timeout: float) -> FakeResponse:
        raise TimeoutError("provider timed out")

    registry = desktop_execution_provider_registry_from_env(
        {"OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://localhost:19091"},
        urlopen=fake_urlopen,
    )

    result = registry.execute_if_routed(
        "desktop.safe_type_text",
        {"text": "hello"},
        tool_request=_sandbox_tool_request(),
        broker=object(),
    )

    assert result is not None
    assert result["ok"] is False
    assert result["error"] == "desktop_execution_provider_transport_failed"
    assert result["blocked_by_desktop_execution_provider"] is True
    assert result["desktop_execution_provider_routed"] is True
    assert result["desktop_execution_provider"]["adapter_registered"] is True


def test_sandbox_desktop_provider_status_reads_runtime_env(monkeypatch) -> None:
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", "http://127.0.0.1:19091")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_ID", "sandbox-1")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS", "desktop.safe_type_text")

    provider = sandbox_desktop_provider_status()
    route = desktop_execution_route_decision(
        "desktop.safe_type_text",
        policy={"mode": "sandbox_preferred"},
        execution_mode={
            "mode": "supervised_live",
            "foreground_control": True,
            "keyboard_mouse_capture": True,
            "sandbox_recommended": True,
            "isolation": "sandbox_desktop",
        },
    )

    assert provider["available"] is True
    assert provider["adapter_ready"] is True
    assert provider["provider_id"] == "sandbox-1"
    assert provider["supported_tools"] == ["desktop.safe_type_text"]
    assert provider["health"]["status"] == "not_checked"
    assert route["status"] == "sandbox_ready"
    assert route["selected_provider_id"] == "sandbox-1"


def test_local_desktop_provider_status_routes_safe_app_activation(monkeypatch) -> None:
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_EXECUTE_URL", raising=False)
    provider = sandbox_desktop_provider_status({"desktop_provider_local_native": True})
    route = desktop_execution_route_decision(
        "app.open",
        policy={"mode": "preview_input"},
        execution_mode={
            "mode": "supervised_live",
            "foreground_control": True,
            "keyboard_mouse_capture": False,
            "sandbox_recommended": True,
            "isolation": "none",
        },
        metadata={
            "desktop_provider_route_foreground": True,
            "desktop_provider_local_native": True,
        },
    )
    unsupported_input_route = desktop_execution_route_decision(
        "desktop.safe_type_text",
        policy={"mode": "preview_input"},
        execution_mode={
            "mode": "supervised_live",
            "foreground_control": True,
            "keyboard_mouse_capture": True,
            "sandbox_recommended": True,
            "isolation": "none",
        },
        metadata={
            "desktop_provider_route_foreground": True,
            "desktop_provider_local_native": True,
        },
    )

    assert provider["available"] is True
    assert provider["adapter_ready"] is True
    assert provider["provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert provider["provider_id"] == LOCAL_DESKTOP_PROVIDER_ID
    assert "app.open" in provider["supported_tools"]
    assert "desktop.safe_type_text" not in provider["supported_tools"]
    assert route["status"] == "sandbox_ready"
    assert route["selected_provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert route["selected_provider_id"] == LOCAL_DESKTOP_PROVIDER_ID
    assert unsupported_input_route["status"] == "sandbox_tool_not_supported"
