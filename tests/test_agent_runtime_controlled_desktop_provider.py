"""Tests for the loopback controlled desktop provider harness."""

from __future__ import annotations

import json
import threading
from typing import Any

from apps.shell.agent.runtime.controlled_desktop_provider import (
    ControlledDesktopProvider,
    build_controlled_desktop_provider_server,
    main,
)
from apps.shell.agent.runtime.desktop_execution_providers import (
    desktop_execution_provider_registry_from_env,
    desktop_execution_provider_status_from_env,
)
from apps.shell.agent.runtime.isolated_desktop_provider import (
    IsolatedDesktopProvider,
    build_isolated_desktop_provider_server,
    main as isolated_main,
)


def test_controlled_desktop_provider_status_and_manifest(capsys) -> None:
    status_code = main(
        [
            "--manifest",
            "--provider-id",
            "provider-control",
            "--tool",
            "desktop.safe_type_text",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert status_code == 0
    assert payload["ok"] is True
    assert payload["provider_id"] == "provider-control"
    assert payload["execution_mode"] == "controlled_desktop"
    assert payload["foreground_mutation_supported"] is True
    assert payload["keyboard_mouse_capture_supported"] is True
    assert payload["desktop_session_kind"] == "user_foreground"
    assert payload["desktop_session_isolated"] is False
    assert payload["foreground_takeover_required"] is True
    assert payload["supported_tools"] == ["desktop.safe_type_text"]
    assert payload["environment"]["keyboard_mouse_capture"] == (
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED"
    )
    assert payload["entrypoint"]["script"] == "scripts/run_controlled_desktop_provider.py"
    assert "desktop.safe_type_text" in payload["safety"]["approval_required_tools"]


def test_controlled_desktop_provider_requires_approval_for_keyboard_mouse() -> None:
    provider = ControlledDesktopProvider(supported_tools=["desktop.safe_type_text"])

    result = provider.execute("desktop.safe_type_text", {"text": "hello"})

    assert result["ok"] is False
    assert result["error"] == "desktop_provider_tool_approval_required"
    assert result["blocking_conditions"] == ["desktop_provider_tool_approval_required"]


def test_controlled_desktop_provider_executes_approved_safe_type(monkeypatch) -> None:
    calls: list[str] = []

    def fake_safe_type(text: str) -> dict[str, Any]:
        calls.append(text)
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "typed",
            "data": {"character_count": len(text)},
        }

    monkeypatch.setattr(
        "apps.shell.agent.runtime.controlled_desktop_provider.desktop.desktop_safe_type_text",
        fake_safe_type,
    )
    provider = ControlledDesktopProvider(supported_tools=["desktop.safe_type_text"])

    result = provider.execute(
        "desktop.safe_type_text",
        {"text": "hello"},
        approved=True,
    )

    assert result["ok"] is True
    assert calls == ["hello"]
    assert result["controlled_desktop_provider"]["provider_id"] == (
        "local-controlled-desktop"
    )
    assert result["controlled_desktop_provider"]["keyboard_mouse_capture_supported"] is True
    assert "headless_desktop_provider" not in result


def test_controlled_desktop_provider_works_through_runtime_adapter(monkeypatch) -> None:
    calls: list[str] = []

    def fake_safe_type(text: str) -> dict[str, Any]:
        calls.append(text)
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "typed through provider",
            "data": {"character_count": len(text)},
        }

    monkeypatch.setattr(
        "apps.shell.agent.runtime.controlled_desktop_provider.desktop.desktop_safe_type_text",
        fake_safe_type,
    )
    provider = ControlledDesktopProvider(
        provider_id="provider-control",
        supported_tools=["desktop.safe_type_text"],
    )
    server = build_controlled_desktop_provider_server(
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
            "OHA_YACHIYO_DESKTOP_PROVIDER_ID": "provider-control",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN": "secret",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": "desktop.safe_type_text",
        }
        status = desktop_execution_provider_status_from_env(env, probe_health=True)
        registry = desktop_execution_provider_registry_from_env(env)
        result = registry.execute_if_routed(
            "desktop.safe_type_text",
            {"text": "hello"},
            tool_request={
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_route": {
                    "route_id": "desktop-route:desktop.safe_type_text",
                    "tool_name": "desktop.safe_type_text",
                    "requested_mode": "sandbox_preferred",
                    "selected_provider_kind": "sandbox_desktop",
                    "selected_provider_id": "provider-control",
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
                    "provider_id": "provider-control",
                    "status": "available",
                    "supported_tools": ["desktop.safe_type_text"],
                    "keyboard_mouse_capture_supported": True,
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
    assert status["keyboard_mouse_capture_supported"] is True
    assert status["health"]["keyboard_mouse_capture_supported"] is True
    assert status["desktop_session_kind"] == "user_foreground"
    assert status["desktop_session_isolated"] is False
    assert status["foreground_takeover_required"] is True
    assert result is not None
    assert result["ok"] is True
    assert calls == ["hello"]
    assert result["desktop_execution_provider_routed"] is True
    assert result["desktop_execution_provider"]["provider_id"] == "provider-control"
    assert result["controlled_desktop_provider"]["execution_mode"] == "controlled_desktop"


def test_isolated_desktop_provider_status_and_manifest(capsys) -> None:
    status_code = isolated_main(
        [
            "--manifest",
            "--provider-id",
            "provider-isolated",
            "--tool",
            "desktop.safe_type_text",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert status_code == 0
    assert payload["ok"] is True
    assert payload["provider_id"] == "provider-isolated"
    assert payload["execution_mode"] == "isolated_desktop"
    assert payload["foreground_mutation_supported"] is True
    assert payload["keyboard_mouse_capture_supported"] is True
    assert payload["desktop_session_kind"] == "isolated_desktop"
    assert payload["desktop_session_isolated"] is True
    assert payload["foreground_takeover_required"] is False
    assert payload["entrypoint"]["script"] == "scripts/run_isolated_desktop_provider.py"
    assert "desktop.safe_type_text" in payload["safety"]["approval_required_tools"]


def test_isolated_desktop_provider_requires_approval_for_keyboard_mouse() -> None:
    provider = IsolatedDesktopProvider(supported_tools=["desktop.safe_type_text"])

    result = provider.execute("desktop.safe_type_text", {"text": "hello"})

    assert result["ok"] is False
    assert result["error"] == "desktop_provider_tool_approval_required"
    assert result["blocking_conditions"] == ["desktop_provider_tool_approval_required"]


def test_isolated_desktop_provider_models_discover_operate_verify_loop() -> None:
    provider = IsolatedDesktopProvider(
        supported_tools=[
            "desktop.open_app",
            "desktop.read_ui",
            "desktop.click_ui_element",
            "desktop.safe_type_text",
            "desktop.verify",
        ],
    )

    opened = provider.execute(
        "desktop.open_app",
        {"app_name": "Apple Music"},
        approved=True,
    )
    ui = provider.execute(
        "desktop.read_ui",
        {"app_name": "Apple Music"},
        approved=True,
    )
    clicked = provider.execute(
        "desktop.click_ui_element",
        {"target": "Search", "role_filter": "text_field"},
        approved=True,
    )
    typed = provider.execute(
        "desktop.safe_type_text",
        {"text": "morning playlist"},
        approved=True,
    )
    verified = provider.execute(
        "desktop.verify",
        {
            "app_name": "Apple Music",
            "target": "Search",
            "expected_text": "morning playlist",
        },
        approved=True,
    )

    assert opened["data"]["app_name"] == "Apple Music"
    assert opened["data"]["desktop_session_isolated"] is True
    assert any(element["title"] == "Search" for element in ui["data"]["elements"])
    assert clicked["data"]["isolated_event"]["target"] == "Search"
    assert typed["data"]["isolated_event"]["text_buffer"] == "morning playlist"
    assert verified["data"]["verification_passed"] is True
    assert verified["data"]["expected_text_found"] is True
    assert verified["data"]["expected_target_focused"] is True
    assert verified["data"]["foreground_takeover_required"] is False


def test_isolated_desktop_provider_inspects_app_without_foreground_takeover() -> None:
    provider = IsolatedDesktopProvider(
        supported_tools=[
            "desktop.inspect_app",
            "app.open",
            "desktop.read_ui",
        ],
    )

    inspected = provider.execute(
        "desktop.inspect_app",
        {"app_name": "PixelForge", "open_if_needed": True, "focus": True},
        approved=True,
    )

    assert inspected["ok"] is True
    assert inspected["data"]["app_name"] == "PixelForge"
    assert inspected["data"]["running"] is True
    assert inspected["data"]["focus_verified"] is True
    assert inspected["data"]["ready_for_foreground_action"] is True
    assert inspected["data"]["desktop_session_isolated"] is True
    assert inspected["data"]["foreground_takeover_required"] is False
    assert inspected["isolated_desktop_provider"]["desktop_session_isolated"] is True
    assert inspected["controlled_desktop_provider"]["foreground_takeover_required"] is False
    assert inspected["data"]["ui_elements"]["data"]["elements"]


def test_isolated_desktop_provider_works_through_runtime_adapter() -> None:
    provider = IsolatedDesktopProvider(
        provider_id="provider-isolated",
        supported_tools=["desktop.safe_type_text"],
    )
    server = build_isolated_desktop_provider_server(
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
            "OHA_YACHIYO_DESKTOP_PROVIDER_ID": "provider-isolated",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN": "secret",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": "desktop.safe_type_text",
        }
        status = desktop_execution_provider_status_from_env(env, probe_health=True)
        registry = desktop_execution_provider_registry_from_env(env)
        result = registry.execute_if_routed(
            "desktop.safe_type_text",
            {"text": "hello"},
            tool_request={
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_route": {
                    "route_id": "desktop-route:desktop.safe_type_text",
                    "tool_name": "desktop.safe_type_text",
                    "requested_mode": "sandbox_preferred",
                    "selected_provider_kind": "sandbox_desktop",
                    "selected_provider_id": "provider-isolated",
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
                    "provider_id": "provider-isolated",
                    "status": "available",
                    "supported_tools": ["desktop.safe_type_text"],
                    "keyboard_mouse_capture_supported": True,
                    "desktop_session_kind": "isolated_desktop",
                    "desktop_session_isolated": True,
                    "foreground_takeover_required": False,
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
    assert status["keyboard_mouse_capture_supported"] is True
    assert status["desktop_session_kind"] == "isolated_desktop"
    assert status["desktop_session_isolated"] is True
    assert status["foreground_takeover_required"] is False
    assert result is not None
    assert result["ok"] is True
    assert result["desktop_execution_provider_routed"] is True
    assert result["desktop_execution_provider"]["provider_id"] == "provider-isolated"
    assert result["isolated_desktop_provider"]["desktop_session_isolated"] is True
    assert result["controlled_desktop_provider"]["execution_mode"] == "isolated_desktop"
