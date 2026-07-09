"""Tests for desktop execution provider adapters."""

from __future__ import annotations

import json
from typing import Any

from apps.shell.agent.runtime.desktop_execution_providers import (
    DesktopExecutionProviderRegistry,
    LocalDesktopExecutionProviderAdapter,
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


def test_desktop_provider_registry_blocks_loopback_backend_even_with_ready_route() -> None:
    requests: list[dict[str, Any]] = []

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        requests.append({"url": request.full_url, "timeout": timeout})
        return FakeResponse({"result": {"ok": True, "data": {"typed": True}}})

    registry = desktop_execution_provider_registry_from_env(
        {
            "OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://127.0.0.1:19091",
            "OHA_YACHIYO_DESKTOP_PROVIDER_ID": "sandbox-1",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": "desktop.safe_type_text",
        },
        urlopen=fake_urlopen,
    )
    tool_request = _sandbox_tool_request()
    tool_request["desktop_execution_route"].update(
        {
            "desktop_backend_kind": "loopback_session_harness",
            "desktop_backend_is_loopback": True,
            "requires_real_virtual_desktop_backend": True,
        }
    )
    tool_request["sandbox_provider"].update(
        {
            "desktop_backend_kind": "loopback_session_harness",
            "desktop_backend_is_loopback": True,
            "requires_real_virtual_desktop_backend": True,
        }
    )

    result = registry.execute_if_routed(
        "desktop.safe_type_text",
        {"text": "hello"},
        tool_request=tool_request,
        broker=object(),
        approved=True,
    )

    assert result is not None
    assert result["ok"] is False
    assert result["status"] == "real_virtual_desktop_provider_required"
    assert result["error"] == "desktop_execution_provider_simulated_backend"
    assert result["desktop_execution_provider_routed"] is True
    assert result["desktop_execution_provider"]["adapter_registered"] is True
    assert result["simulated_desktop_provider"] is True
    assert result["requires_real_virtual_desktop_backend"] is True
    assert result["blocking_conditions"] == [
        "loopback_desktop_backend",
        "real_virtual_desktop_backend_required",
    ]
    recovery = result["recovery_actions"][0]
    assert recovery["tool"] == "desktop.provider_session.start"
    assert recovery["input"]["requires_real_virtual_desktop_backend"] is True
    assert recovery["input"]["tools"] == ["desktop.safe_type_text"]
    assert recovery["permission_target"] == "real_virtual_desktop_provider"
    assert recovery["metadata"]["requires_real_virtual_desktop_backend"] is True
    assert recovery["metadata"]["runtime_replan_auto_start_eligible"] is False
    assert requests == []


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
    assert result["local_desktop_provider"]["transport"] == "runtime_tool_broker"
    assert result["desktop_execution_evidence"]["transport"] == "runtime_tool_broker"
    assert result["desktop_execution_evidence"]["effect"] == "app_launch"
    assert result["desktop_execution_evidence"]["keyboard_mouse_capture"] is False
    assert calls == [("app.open", {"app_name": "Music"}, False)]


def test_local_provider_route_ignores_unselected_loopback_session() -> None:
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
            return {"ok": True, "action": name, "data": {"played": True}}

    registry = desktop_execution_provider_registry_from_env({})
    tool_request = _local_tool_request(
        "media.music_app_open_and_play",
        {"app_name": "Music"},
    )
    tool_request["desktop_provider_session"] = {
        "provider_id": "local-isolated-desktop",
        "running": True,
        "desktop_session_kind": "isolated_desktop",
        "desktop_session_isolated": True,
        "foreground_takeover_required": False,
        "desktop_backend_kind": "loopback_session_harness",
        "desktop_backend_is_loopback": True,
        "requires_real_virtual_desktop_backend": True,
    }

    result = registry.execute_if_routed(
        "media.music_app_open_and_play",
        {"app_name": "Music"},
        tool_request=tool_request,
        broker=FakeBroker(),
    )

    assert result is not None
    assert result["ok"] is True
    assert result["desktop_execution_provider"]["provider_kind"] == (
        LOCAL_DESKTOP_PROVIDER_KIND
    )
    assert result["desktop_execution_evidence"]["effect"] == "media_control"
    assert "simulated_desktop_provider" not in result
    assert calls == [
        ("media.music_app_open_and_play", {"app_name": "Music"}, False)
    ]


def test_local_provider_direct_fallback_executes_low_risk_discovery(
    monkeypatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    def fake_list_apps(query: str = "", limit: Any = 200) -> dict[str, Any]:
        calls.append((query, limit))
        return {
            "ok": True,
            "action": "desktop.list_apps",
            "summary": "Installed apps matching Music: Music",
            "data": {
                "query": query,
                "apps": [{"name": "Music", "path": "/System/Applications/Music.app"}],
                "count": 1,
            },
            "permission_error": False,
            "fallback_used": False,
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.list_apps",
        fake_list_apps,
    )
    registry = DesktopExecutionProviderRegistry([LocalDesktopExecutionProviderAdapter()])
    tool_request = _local_tool_request("desktop.list_apps", {"query": "Music", "limit": 5})

    result = registry.execute_if_routed(
        "desktop.list_apps",
        {"query": "Music", "limit": 5},
        tool_request=tool_request,
        broker=object(),
    )

    assert result is not None
    assert result["ok"] is True
    assert result["desktop_execution_provider_routed"] is True
    assert result["local_desktop_provider"]["transport"] == "direct_local_tools"
    assert result["desktop_execution_evidence"] == {
        "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
        "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
        "transport": "direct_local_tools",
        "tool": "desktop.list_apps",
        "ok": True,
        "effect": "desktop_app_discovery",
        "user_foreground_session": True,
        "keyboard_mouse_capture": False,
        "permission_error": False,
        "fallback_used": False,
        "query": "Music",
    }
    assert calls == [("Music", 5)]


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
    assert status["foreground_mutation_supported"] is True
    assert status["keyboard_mouse_capture_supported"] is True
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
                "keyboard_mouse_capture_supported": True,
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
    assert status["foreground_mutation_supported"] is True
    assert status["keyboard_mouse_capture_supported"] is True
    assert status["health"]["keyboard_mouse_capture_supported"] is True
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


def test_desktop_provider_registry_refreshes_adapter_from_runtime_env(monkeypatch) -> None:
    requests: list[dict[str, Any]] = []

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        requests.append(
            {
                "url": request.full_url,
                "timeout": timeout,
                "payload": json.loads(request.data.decode("utf-8")),
            }
        )
        return FakeResponse({"result": {"ok": True, "typed": True}})

    monkeypatch.setattr(
        "apps.shell.agent.runtime.desktop_execution_providers.urlopen_with_bundled_ca",
        fake_urlopen,
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", "http://127.0.0.1:19093")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_ID", "local-isolated-desktop")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "desktop.safe_type_text",
    )
    registry = DesktopExecutionProviderRegistry()
    tool_request = _sandbox_tool_request()
    tool_request["desktop_execution_route"]["selected_provider_id"] = "local-isolated-desktop"
    tool_request["sandbox_provider"]["provider_id"] = "local-isolated-desktop"

    result = registry.execute_if_routed(
        "desktop.safe_type_text",
        {"text": "hello"},
        tool_request=tool_request,
        broker=object(),
        approved=True,
    )

    assert result is not None
    assert result["ok"] is True
    assert result["desktop_execution_provider"]["adapter_registered"] is True
    assert result["desktop_execution_provider"]["provider_id"] == "local-isolated-desktop"
    assert requests[0]["url"] == "http://127.0.0.1:19093/tools/execute"


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
    assert provider["foreground_mutation_supported"] is True
    assert provider["keyboard_mouse_capture_supported"] is True
    assert provider["health"]["status"] == "not_checked"
    assert route["status"] == "sandbox_ready"
    assert route["selected_provider_id"] == "sandbox-1"


def test_env_control_provider_can_advertise_keyboard_mouse_capture(monkeypatch) -> None:
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", "http://127.0.0.1:19091")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_ID", "sandbox-control")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS", "desktop.safe_type_text")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
        "true",
    )
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
        metadata={"desktop_provider_route_foreground": True},
    )

    assert provider["provider_id"] == "sandbox-control"
    assert provider["keyboard_mouse_capture_supported"] is True
    assert route["status"] == "sandbox_ready"
    assert route["selected_provider_id"] == "sandbox-control"


def test_env_control_provider_can_block_keyboard_mouse_until_sandbox_ready(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", "http://127.0.0.1:19091")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_ID", "sandbox-readonly")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS", "desktop.safe_type_text")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
        "false",
    )
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_SANDBOX_FOR",
        "desktop.safe_type_text",
    )
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
        metadata={"desktop_provider_route_foreground": True},
    )

    assert provider["keyboard_mouse_capture_supported"] is False
    assert provider["requires_real_sandbox_for"] == ["desktop.safe_type_text"]
    assert route["status"] == "sandbox_keyboard_mouse_provider_required"


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
    inspect_route = desktop_execution_route_decision(
        "desktop.inspect_app",
        policy={"mode": "preview_input"},
        execution_mode={
            "mode": "read_only_observation",
            "foreground_control": False,
            "keyboard_mouse_capture": False,
            "sandbox_recommended": False,
            "isolation": "none",
        },
        metadata={
            "desktop_provider_route_readonly": True,
            "desktop_provider_local_native": True,
        },
    )

    assert provider["available"] is True
    assert provider["adapter_ready"] is True
    assert provider["provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert provider["provider_id"] == LOCAL_DESKTOP_PROVIDER_ID
    assert "app.open" in provider["supported_tools"]
    assert "desktop.inspect_app" in provider["supported_tools"]
    assert "desktop.safe_type_text" not in provider["supported_tools"]
    assert provider["foreground_mutation_supported"] is True
    assert provider["keyboard_mouse_capture_supported"] is False
    assert "desktop.safe_type_text" in provider["requires_real_sandbox_for"]
    assert route["status"] == "provider_ready"
    assert route["selected_provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert route["selected_provider_id"] == LOCAL_DESKTOP_PROVIDER_ID
    assert route["foreground_takeover_required"] is True
    assert route["requires_user_foreground_session"] is True
    assert route["user_foreground_takeover_risk"] is True
    assert route["provider_execution_required"] is True
    assert route["sandbox_required"] is False
    assert route["reason"] == (
        "Foreground desktop action can be routed through the local_desktop "
        "provider, but that provider may use the user's foreground desktop "
        "session."
    )
    assert inspect_route["status"] == "provider_ready"
    assert inspect_route["selected_provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert inspect_route["foreground_takeover_required"] is True
    assert inspect_route["requires_user_foreground_session"] is True
    assert inspect_route["user_foreground_takeover_risk"] is False
    assert inspect_route["reason"] == (
        "Read-only desktop discovery can be routed through the local_desktop "
        "provider. It does not request keyboard or mouse capture, but it "
        "observes the user's desktop session."
    )
    assert unsupported_input_route["status"] == "sandbox_keyboard_mouse_provider_required"
    assert unsupported_input_route["blocking_conditions"] == [
        "sandbox_keyboard_mouse_provider_required"
    ]


def test_local_low_risk_routes_win_over_running_loopback_provider(monkeypatch) -> None:
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", "http://127.0.0.1:19093")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_ID", "local-isolated-desktop")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "desktop.list_apps,app.open,media.music_app_open_and_play,desktop.safe_type_text",
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_KIND", "sandbox_desktop")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND", "isolated_desktop")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED", "true")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED", "false")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND", "loopback_session_harness")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK", "true")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND",
        "true",
    )

    common_metadata = {
        "desktop_provider_route_foreground": True,
        "desktop_provider_route_readonly": True,
        "desktop_provider_local_native": True,
    }
    list_apps_route = desktop_execution_route_decision(
        "desktop.list_apps",
        policy={"mode": "preview_input", "source": "daily_chat"},
        execution_mode={
            "mode": "tool_native",
            "foreground_control": False,
            "keyboard_mouse_capture": False,
            "sandbox_recommended": False,
            "isolation": "none",
        },
        metadata=common_metadata,
    )
    open_route = desktop_execution_route_decision(
        "app.open",
        policy={"mode": "preview_input", "source": "daily_chat"},
        execution_mode={
            "mode": "supervised_live",
            "foreground_control": True,
            "keyboard_mouse_capture": False,
            "sandbox_recommended": True,
            "isolation": "none",
        },
        metadata=common_metadata,
    )
    input_route = desktop_execution_route_decision(
        "desktop.safe_type_text",
        policy={"mode": "preview_input", "source": "daily_chat"},
        execution_mode={
            "mode": "supervised_live",
            "foreground_control": True,
            "keyboard_mouse_capture": True,
            "sandbox_recommended": True,
            "isolation": "sandbox_desktop",
        },
        metadata=common_metadata,
    )

    assert list_apps_route["status"] == "provider_ready"
    assert list_apps_route["selected_provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert list_apps_route["selected_provider_id"] == LOCAL_DESKTOP_PROVIDER_ID
    assert list_apps_route.get("desktop_backend_kind") != "loopback_session_harness"
    assert open_route["status"] == "provider_ready"
    assert open_route["selected_provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert open_route["selected_provider_id"] == LOCAL_DESKTOP_PROVIDER_ID
    assert input_route["status"] == "real_virtual_desktop_provider_required"
    assert input_route["selected_provider_id"] == "local-isolated-desktop"
