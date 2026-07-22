"""Fail-closed contracts for background versus user-foreground desktop control."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell.agent.runtime.cua_background_provider import (
    CUA_BACKGROUND_PROVIDER_KIND,
)
from apps.shell.agent.runtime.desktop_execution_providers import (
    LOCAL_DESKTOP_PROVIDER_ID,
    LOCAL_DESKTOP_PROVIDER_KIND,
    DesktopExecutionProviderRegistry,
    LocalDesktopExecutionProviderAdapter,
    desktop_execution_provider_unavailable_result,
)
from apps.shell.agent.runtime import tool_execution as tool_execution_module
from apps.shell.yachiyo_agent import desktop_execution_policy as policy_module
from apps.shell.yachiyo_agent import isolated_provider_session as session_module
from apps.shell.yachiyo_agent.desktop_execution_policy import (
    daily_entrypoint_desktop_execution_policy,
    desktop_execution_route_decision,
)
from apps.shell.yachiyo_agent.policy import desktop_tool_execution_mode


class FakeBroker:
    """Records calls without touching any real application or desktop API."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], bool]] = []

    def call(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        self.calls.append((name, dict(payload), bool(approved)))
        return {
            "ok": True,
            "action": name,
            "data": dict(payload),
        }


def _missing_cua_status() -> dict[str, Any]:
    return {
        "configured": False,
        "available": False,
        "adapter_ready": False,
        "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
        "provider_id": "cua-driver",
        "status": "provider_required",
        "setup_state": "required",
        "reason": "Cua Driver is not installed.",
        "blocking_conditions": ["cua_driver_not_installed"],
        "supported_tools": [],
        "desktop_session_kind": "background_desktop",
        "desktop_session_isolated": False,
        "foreground_takeover_required": False,
        "keyboard_mouse_capture_supported": True,
    }


def _ready_cua_status() -> dict[str, Any]:
    return {
        "configured": True,
        "available": True,
        "adapter_ready": True,
        "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
        "provider_id": "cua-driver",
        "status": "available",
        "setup_state": "ready",
        "reason": "Cua Driver background execution is available.",
        "blocking_conditions": [],
        "supported_tools": ["app.open"],
        "desktop_session_kind": "background_desktop",
        "desktop_session_isolated": False,
        "foreground_takeover_required": False,
        "foreground_mutation_supported": True,
        "keyboard_mouse_capture_supported": True,
        "health": {
            "ok": True,
            "checked": True,
            "status": "healthy",
            "blocking_conditions": [],
            "supported_tools": ["app.open"],
        },
    }


def _local_provider(tool_name: str) -> dict[str, Any]:
    return {
        "available": True,
        "adapter_ready": True,
        "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
        "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
        "status": "available",
        "supported_tools": [tool_name],
        "desktop_session_kind": "user_foreground",
        "desktop_session_isolated": False,
        "foreground_takeover_required": True,
        "foreground_mutation_supported": True,
        "keyboard_mouse_capture_supported": True,
    }


def _local_provider_route(tool_name: str) -> dict[str, Any]:
    return {
        "route_id": f"desktop-route:{tool_name}",
        "tool_name": tool_name,
        "requested_mode": "preview_input",
        "selected_provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
        "selected_provider_id": LOCAL_DESKTOP_PROVIDER_ID,
        "status": "provider_ready",
        "can_execute": True,
        "can_auto_start": True,
        "provider_execution_required": True,
        "sandbox_required": False,
        "foreground_takeover_allowed": False,
        "foreground_takeover_required": True,
        "requires_user_foreground_session": True,
        "user_foreground_takeover_risk": True,
        "blocking_conditions": [],
    }


def _local_tool_request(
    tool_name: str,
    payload: dict[str, Any],
    *,
    foreground_authorized: bool = False,
) -> dict[str, Any]:
    request = {
        "tool": tool_name,
        "input": dict(payload),
        "desktop_execution_policy": daily_entrypoint_desktop_execution_policy(
            surface="chat"
        ),
        "desktop_execution_route": _local_provider_route(tool_name),
        "sandbox_provider": _local_provider(tool_name),
    }
    if foreground_authorized:
        request["allow_user_foreground_takeover"] = True
        request["desktop_execution_policy"] = {
            "mode": "allow",
            "allow_live_foreground": True,
            "prefer_background_desktop": False,
            "prefer_isolated_desktop": False,
            "avoid_user_foreground_takeover": False,
            "require_sandbox_for_keyboard_mouse": False,
        }
        request["desktop_execution_route"]["foreground_takeover_allowed"] = True
    return request


def test_daily_background_policy_keeps_missing_cua_route_off_local_desktop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        policy_module,
        "cua_background_provider_status",
        lambda **_kwargs: _missing_cua_status(),
    )
    policy = daily_entrypoint_desktop_execution_policy(surface="chat")

    route = desktop_execution_route_decision(
        "app.open",
        policy=policy,
        execution_mode=desktop_tool_execution_mode("app.open"),
        metadata={
            # A stale persisted local snapshot must not override the daily lane.
            "sandbox_provider": _local_provider("app.open"),
            "desktop_provider_local_native": True,
        },
    )

    assert policy["prefer_background_desktop"] is True
    assert route["selected_provider_kind"] == CUA_BACKGROUND_PROVIDER_KIND
    assert route["selected_provider_id"] == "cua-driver"
    assert route["status"] == "provider_required"
    assert route["can_execute"] is False
    assert route["can_auto_start"] is False
    assert route["fallback_mode"] == "user_handoff"
    assert route["blocking_conditions"] == ["cua_driver_not_installed"]
    assert route["selected_provider_kind"] != LOCAL_DESKTOP_PROVIDER_KIND


@pytest.mark.parametrize("stale_route", [False, True], ids=("new-route", "stale-route"))
def test_tool_execution_probes_background_provider_before_freezing_route(
    monkeypatch: pytest.MonkeyPatch,
    stale_route: bool,
) -> None:
    probes: list[bool] = []

    def status(*, probe_health: bool = False, **_kwargs: Any) -> dict[str, Any]:
        probes.append(probe_health)
        return _ready_cua_status() if probe_health else _missing_cua_status()

    monkeypatch.setattr(policy_module, "cua_background_provider_status", status)
    policy = daily_entrypoint_desktop_execution_policy(surface="chat")
    tool_request = {
        "tool": "app.open",
        "input": {"app_name": "TextEdit", "bring_to_front": False},
        "desktop_execution_policy": policy,
    }
    if stale_route:
        tool_request["desktop_execution_route"] = {
            "route_id": "desktop-route:app.open",
            "tool_name": "app.open",
            "selected_provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
            "selected_provider_id": "cua-driver",
            "status": "provider_required",
            "can_execute": False,
            "blocking_conditions": ["sandbox_desktop_provider_required"],
        }

    request = tool_execution_module._tool_request_with_desktop_execution_route(
        "app.open",
        tool_request,
    )

    assert probes == [True]
    assert request["desktop_execution_route"]["status"] == "provider_ready"
    assert request["desktop_execution_route"]["can_execute"] is True
    assert request["sandbox_provider"]["health"]["checked"] is True


def test_tool_execution_revalidates_ready_background_route_before_safety_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes: list[bool] = []

    def status(*, probe_health: bool = False, **_kwargs: Any) -> dict[str, Any]:
        probes.append(probe_health)
        return _ready_cua_status() if probe_health else _missing_cua_status()

    monkeypatch.setattr(policy_module, "cua_background_provider_status", status)
    policy = daily_entrypoint_desktop_execution_policy(surface="chat")
    ready_route = {
        "route_id": "desktop-route:app.open",
        "tool_name": "app.open",
        "selected_provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
        "selected_provider_id": "cua-driver",
        "status": "provider_ready",
        "can_execute": True,
        "provider_execution_required": True,
        "blocking_conditions": [],
    }

    request = tool_execution_module._tool_request_with_desktop_execution_route(
        "app.open",
        {
            "tool": "app.open",
            "input": {"app_name": "TextEdit", "bring_to_front": False},
            "desktop_execution_policy": policy,
            "desktop_execution_route": ready_route,
        },
    )

    assert probes == [True]
    assert request["desktop_execution_route"]["status"] == "provider_ready"
    assert request["desktop_execution_route"]["can_execute"] is True
    assert request["sandbox_provider"]["health"]["checked"] is True


def test_tool_execution_does_not_refresh_real_virtual_desktop_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes: list[bool] = []

    def status(*, probe_health: bool = False, **_kwargs: Any) -> dict[str, Any]:
        probes.append(probe_health)
        return _ready_cua_status()

    monkeypatch.setattr(policy_module, "cua_background_provider_status", status)
    policy = daily_entrypoint_desktop_execution_policy(surface="chat")
    blocked_route = {
        "route_id": "desktop-route:desktop.safe_type_text",
        "tool_name": "desktop.safe_type_text",
        "selected_provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
        "selected_provider_id": "cua-driver",
        "status": "provider_required",
        "can_execute": False,
        "blocking_conditions": ["real_virtual_desktop_backend_required"],
    }

    request = tool_execution_module._tool_request_with_desktop_execution_route(
        "desktop.safe_type_text",
        {
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
            "desktop_execution_policy": policy,
            "desktop_execution_route": blocked_route,
        },
    )

    assert probes == []
    assert request["desktop_execution_route"] == blocked_route


@pytest.mark.parametrize(
    "background_context",
    [
        {
            "desktop_execution_route": {
                "selected_provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
                "selected_provider_id": "cua-driver",
                "status": "provider_ready",
                "can_execute": True,
                "provider_execution_required": True,
                "foreground_takeover_required": False,
            }
        },
        {
            "desktop_execution_route": {
                "selected_provider_kind": "sandbox_desktop",
                "status": "sandbox_desktop_session_required",
                "sandbox_required": True,
            },
            "sandbox_provider": {
                "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
                "provider_id": "cua-driver",
                "available": True,
                "adapter_ready": True,
                "desktop_session_kind": "background_desktop",
                "desktop_session_isolated": False,
                "foreground_takeover_required": False,
                "supported_tools": ["app.open"],
            },
        },
    ],
    ids=("background-route", "background-provider"),
)
def test_background_route_or_provider_never_starts_isolated_session(
    monkeypatch: pytest.MonkeyPatch,
    background_context: dict[str, Any],
) -> None:
    starts: list[dict[str, Any] | None] = []
    monkeypatch.setattr(
        session_module,
        "isolated_desktop_provider_session_status",
        lambda: {"ok": True, "status": "stopped", "running": False},
    )
    monkeypatch.setattr(
        session_module,
        "start_isolated_desktop_provider_session",
        lambda request=None: starts.append(request) or {"ok": True},
    )
    envelope = {
        "requests": [
            {
                "request_id": "request-open",
                "tool_name": "app.open",
                "input": {"app_name": "TextEdit"},
                **background_context,
            }
        ]
    }

    session = session_module.ensure_isolated_desktop_provider_session_for_envelope(
        envelope
    )

    assert session["needed"] is False
    assert session["started"] is False
    assert session["request_ids"] == []
    assert session["tool_names"] == []
    assert starts == []


def test_stale_local_provider_ready_route_cannot_bypass_daily_background_policy() -> None:
    registry = DesktopExecutionProviderRegistry(
        [LocalDesktopExecutionProviderAdapter()]
    )
    broker = FakeBroker()
    tool_request = _local_tool_request("app.open", {"app_name": "TextEdit"})

    result = registry.execute_if_routed(
        "app.open",
        {"app_name": "TextEdit"},
        tool_request=tool_request,
        broker=broker,
        approved=True,
    )

    assert result is not None
    assert result["ok"] is False
    assert result["blocked_by_desktop_execution_provider"] is True
    assert result["blocking_conditions"]
    assert broker.calls == []


def test_daily_quit_foreground_app_missing_cua_never_calls_local_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        policy_module,
        "cua_background_provider_status",
        lambda **_kwargs: _missing_cua_status(),
    )
    policy = daily_entrypoint_desktop_execution_policy(surface="chat")
    route = desktop_execution_route_decision(
        "desktop.quit_app",
        policy=policy,
        execution_mode=desktop_tool_execution_mode("desktop.quit_app"),
        metadata={"desktop_execution_policy": policy},
    )
    tool_request = {
        "tool": "desktop.quit_app",
        "input": {},
        "desktop_execution_policy": policy,
        "desktop_execution_route": route,
        "sandbox_provider": _missing_cua_status(),
    }
    registry = DesktopExecutionProviderRegistry(
        [LocalDesktopExecutionProviderAdapter()]
    )
    broker = FakeBroker()

    result = tool_execution_module._desktop_execution_policy_skip_result(
        "desktop.quit_app",
        tool_request,
        {},
    )
    if result is None:
        result = registry.execute_if_routed(
            "desktop.quit_app",
            {},
            tool_request=tool_request,
            broker=broker,
            approved=True,
        )
    if result is None:
        result = broker.call("desktop.quit_app", {}, approved=True)

    assert result["ok"] is False
    assert result["blocked_by_desktop_execution_policy"] is True
    assert result["desktop_execution_route"]["selected_provider_kind"] == (
        CUA_BACKGROUND_PROVIDER_KIND
    )
    assert broker.calls == []


@pytest.mark.parametrize(
    ("tool_name", "payload"),
    [
        ("app.open", {"app_name": "TextEdit"}),
        ("desktop.safe_type_text", {"text": "hello"}),
    ],
    ids=("foreground-mutation", "keyboard-input"),
)
def test_local_provider_requires_request_level_foreground_authorization(
    tool_name: str,
    payload: dict[str, Any],
) -> None:
    adapter = LocalDesktopExecutionProviderAdapter()
    broker = FakeBroker()
    tool_request = _local_tool_request(tool_name, payload)

    result = adapter.execute(
        tool_name,
        payload,
        tool_request=tool_request,
        route=tool_request["desktop_execution_route"],
        broker=broker,
        # Tool approval is intentionally not foreground-takeover authorization.
        approved=True,
    )

    assert result["ok"] is False
    assert result["blocked_by_desktop_execution_provider"] is True
    failure_text = " ".join(
        [
            str(result.get("status") or ""),
            str(result.get("error") or ""),
            *[str(value) for value in result.get("blocking_conditions") or []],
        ]
    ).lower()
    assert "foreground" in failure_text
    assert broker.calls == []


@pytest.mark.parametrize(
    ("tool_name", "payload"),
    [
        ("app.open", {"app_name": "TextEdit"}),
        ("desktop.safe_type_text", {"text": "hello"}),
    ],
    ids=("foreground-mutation", "keyboard-input"),
)
def test_explicit_request_foreground_authorization_allows_local_provider(
    tool_name: str,
    payload: dict[str, Any],
) -> None:
    adapter = LocalDesktopExecutionProviderAdapter()
    broker = FakeBroker()
    tool_request = _local_tool_request(
        tool_name,
        payload,
        foreground_authorized=True,
    )

    result = adapter.execute(
        tool_name,
        payload,
        tool_request=tool_request,
        route=tool_request["desktop_execution_route"],
        broker=broker,
        approved=False,
    )

    assert result["ok"] is True
    assert broker.calls == [(tool_name, payload, False)]


def test_readonly_local_provider_tool_does_not_require_foreground_authorization() -> None:
    tool_name = "desktop.list_apps"
    payload = {"query": "Music", "limit": 5}
    adapter = LocalDesktopExecutionProviderAdapter()
    broker = FakeBroker()
    tool_request = _local_tool_request(tool_name, payload)

    result = adapter.execute(
        tool_name,
        payload,
        tool_request=tool_request,
        route=tool_request["desktop_execution_route"],
        broker=broker,
    )

    assert result["ok"] is True
    assert broker.calls == [(tool_name, payload, False)]


def test_missing_background_provider_never_offers_isolated_session_start() -> None:
    route = {
        "selected_provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
        "selected_provider_id": "cua-driver",
        "status": "provider_required",
        "can_execute": False,
        "can_auto_start": False,
        "fallback_mode": "user_handoff",
        "blocking_conditions": ["cua_driver_not_installed"],
    }
    provider = _missing_cua_status()

    assert (
        tool_execution_module._desktop_execution_policy_should_offer_session_start(
            route,
            provider,
        )
        is False
    )
    result = desktop_execution_provider_unavailable_result(
        "app.open",
        route={**route, "can_execute": True, "provider_execution_required": True},
        tool_request={"input": {"app_name": "TextEdit"}, "sandbox_provider": provider},
    )

    assert result["recommended_tools"] == []
    assert result["recovery_actions"] == []
    assert "paused" in result["summary"].lower()
