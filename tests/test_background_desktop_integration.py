from __future__ import annotations

import threading
from typing import Any, Mapping

import pytest

import apps.shell.agent.runtime.desktop_execution_providers as provider_module
import apps.shell.yachiyo_agent.desktop_execution_policy as policy_module
from apps.shell.agent.runtime.cua_background_provider import (
    CUA_BACKGROUND_PROVIDER_KIND,
)
from apps.shell.yachiyo_agent import DesktopExecutionModeSnapshot


class _FakeBackgroundAdapter:
    provider_kind = CUA_BACKGROUND_PROVIDER_KIND
    provider_id = "cua-driver"

    def can_execute(
        self,
        tool_name: str,
        route: Mapping[str, Any],
        tool_request: Mapping[str, Any],
    ) -> bool:
        del tool_request
        return (
            tool_name == "desktop.safe_type_text"
            and route.get("selected_provider_id") == self.provider_id
        )

    def execute(
        self,
        tool_name: str,
        payload: Mapping[str, Any],
        *,
        tool_request: Mapping[str, Any],
        route: Mapping[str, Any],
        broker: Any,
        approved: bool = False,
    ) -> dict[str, Any]:
        del tool_request, route, broker
        return {
            "ok": True,
            "tool": tool_name,
            "data": dict(payload),
            "approved": approved,
        }


def _background_tool_request() -> dict[str, Any]:
    return {
        "tool": "desktop.safe_type_text",
        "desktop_execution_route": {
            "tool_name": "desktop.safe_type_text",
            "selected_provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
            "selected_provider_id": "cua-driver",
            "status": "provider_ready",
            "can_execute": True,
            "provider_execution_required": True,
            "foreground_takeover_required": False,
        },
        "sandbox_provider": {
            "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
            "provider_id": "cua-driver",
            "supported_tools": ["desktop.safe_type_text"],
            "desktop_session_kind": "background_desktop",
            "desktop_session_isolated": False,
            "foreground_takeover_required": False,
        },
    }


def test_registry_routes_background_provider_to_optional_adapter(monkeypatch) -> None:
    adapter = _FakeBackgroundAdapter()
    monkeypatch.setattr(
        provider_module,
        "cua_background_provider_adapter_from_env",
        lambda *_args, **_kwargs: adapter,
    )
    registry = provider_module.desktop_execution_provider_registry_from_env({})

    result = registry.execute_if_routed(
        "desktop.safe_type_text",
        {"pid": 42, "text": "hello"},
        tool_request=_background_tool_request(),
        broker=object(),
        approved=True,
    )

    assert result is not None
    assert result["ok"] is True
    assert result["approved"] is True
    assert result["desktop_execution_provider_routed"] is True
    assert result["desktop_execution_provider"]["provider_kind"] == (
        CUA_BACKGROUND_PROVIDER_KIND
    )


def test_registry_refreshes_background_adapter_after_driver_appears(monkeypatch) -> None:
    adapter = _FakeBackgroundAdapter()
    calls = 0

    def factory(*_args: Any, **_kwargs: Any) -> _FakeBackgroundAdapter | None:
        nonlocal calls
        calls += 1
        return None if calls == 1 else adapter

    monkeypatch.setattr(
        provider_module,
        "cua_background_provider_adapter_from_env",
        factory,
    )
    registry = provider_module.desktop_execution_provider_registry_from_env({})

    selected = registry.adapter_for(
        CUA_BACKGROUND_PROVIDER_KIND,
        "desktop.safe_type_text",
        _background_tool_request()["desktop_execution_route"],
        _background_tool_request(),
    )

    assert selected is adapter
    assert calls == 2


def test_registry_replaces_same_id_background_adapter_that_is_unreachable(
    monkeypatch,
) -> None:
    class RejectingAdapter(_FakeBackgroundAdapter):
        def __init__(self) -> None:
            self.closed = False

        def can_execute(
            self,
            tool_name: str,
            route: Mapping[str, Any],
            tool_request: Mapping[str, Any],
        ) -> bool:
            del tool_name, route, tool_request
            return False

        def close(self) -> None:
            self.closed = True

        def health(self) -> dict[str, Any]:
            return {
                "checked": True,
                "ok": False,
                "status": "unreachable",
                "blocking_conditions": [
                    "desktop_execution_provider_unreachable"
                ],
            }

    stale = RejectingAdapter()
    healthy = _FakeBackgroundAdapter()
    monkeypatch.setattr(
        provider_module,
        "cua_background_provider_adapter_from_env",
        lambda *_args, **_kwargs: healthy,
    )
    registry = provider_module.DesktopExecutionProviderRegistry([stale])

    selected = registry.adapter_for(
        CUA_BACKGROUND_PROVIDER_KIND,
        "desktop.safe_type_text",
        _background_tool_request()["desktop_execution_route"],
        _background_tool_request(),
    )

    assert selected is healthy
    assert stale.closed is False
    assert registry._adapters[CUA_BACKGROUND_PROVIDER_KIND] == [healthy]
    registry.close()
    assert stale.closed is True


def test_registry_reuses_same_electron_bridge_client_without_accumulating_transports(
    monkeypatch,
) -> None:
    class BridgeClient:
        transport_kind = "electron_bridge"
        transport_identity = (
            "electron-bridge-v1",
            "tcp://127.0.0.1:43123",
            "generation-1",
        )

    class BridgeAdapter(_FakeBackgroundAdapter):
        def __init__(self) -> None:
            self.client = BridgeClient()
            self.closed = False

        def close(self) -> None:
            self.closed = True

    existing = BridgeAdapter()
    redundant = BridgeAdapter()
    factory_calls = 0

    def factory(*_args: Any, **_kwargs: Any) -> BridgeAdapter:
        nonlocal factory_calls
        factory_calls += 1
        return redundant

    monkeypatch.setattr(
        provider_module,
        "cua_background_provider_adapter_from_env",
        factory,
    )
    registry = provider_module.DesktopExecutionProviderRegistry([existing])

    first = registry._refresh_env_adapter(CUA_BACKGROUND_PROVIDER_KIND)
    second = registry.adapter_for(
        CUA_BACKGROUND_PROVIDER_KIND,
        "desktop.safe_type_text",
        _background_tool_request()["desktop_execution_route"],
        _background_tool_request(),
    )

    assert first is existing
    assert second is existing
    assert factory_calls == 1
    assert redundant.closed is True
    assert existing.closed is False
    assert registry._adapters[CUA_BACKGROUND_PROVIDER_KIND] == [existing]
    assert registry._retired_adapters == []


def test_registry_replaces_electron_bridge_when_generation_changes(
    monkeypatch,
) -> None:
    class BridgeClient:
        transport_kind = "electron_bridge"

        def __init__(self, generation: str) -> None:
            self.transport_identity = (
                "electron-bridge-v1",
                "tcp://127.0.0.1:43123",
                generation,
            )

    class BridgeAdapter(_FakeBackgroundAdapter):
        def __init__(self, generation: str) -> None:
            self.client = BridgeClient(generation)
            self.closed = False

        def close(self) -> None:
            self.closed = True

    previous = BridgeAdapter("generation-1")
    current = BridgeAdapter("generation-2")
    monkeypatch.setattr(
        provider_module,
        "cua_background_provider_adapter_from_env",
        lambda *_args, **_kwargs: current,
    )
    registry = provider_module.DesktopExecutionProviderRegistry([previous])

    selected = registry._refresh_env_adapter(CUA_BACKGROUND_PROVIDER_KIND)

    assert selected is current
    assert current.closed is False
    assert previous.closed is False
    assert registry._adapters[CUA_BACKGROUND_PROVIDER_KIND] == [current]
    assert registry._retired_adapters == [previous]


def test_registry_does_not_replace_healthy_stateful_adapter_on_capability_miss(
    monkeypatch,
) -> None:
    class StatefulAdapter(_FakeBackgroundAdapter):
        def __init__(self) -> None:
            self.closed = False
            self.target_state = {"task-1": {"pid": 42}}

        def close(self) -> None:
            self.closed = True

        def health(self) -> dict[str, Any]:
            return {"checked": True, "ok": True, "status": "healthy"}

    adapter = StatefulAdapter()
    factory_calls = 0

    def factory(*_args: Any, **_kwargs: Any) -> _FakeBackgroundAdapter:
        nonlocal factory_calls
        factory_calls += 1
        return _FakeBackgroundAdapter()

    monkeypatch.setattr(
        provider_module,
        "cua_background_provider_adapter_from_env",
        factory,
    )
    registry = provider_module.DesktopExecutionProviderRegistry([adapter])

    selected = registry.adapter_for(
        CUA_BACKGROUND_PROVIDER_KIND,
        "desktop.safe_key",
        _background_tool_request()["desktop_execution_route"],
        _background_tool_request(),
    )

    assert selected is None
    assert factory_calls == 0
    assert adapter.closed is False
    assert adapter.target_state == {"task-1": {"pid": 42}}
    assert registry._adapters[CUA_BACKGROUND_PROVIDER_KIND] == [adapter]


@pytest.mark.parametrize("blocked_probe", ["can_execute", "health"])
def test_registry_does_not_hold_global_lock_during_provider_probe(
    blocked_probe: str,
) -> None:
    probe_entered = threading.Event()
    release_probe = threading.Event()
    worker_errors: list[BaseException] = []

    class BlockingAdapter(_FakeBackgroundAdapter):
        def can_execute(
            self,
            tool_name: str,
            route: Mapping[str, Any],
            tool_request: Mapping[str, Any],
        ) -> bool:
            del tool_name, route, tool_request
            if blocked_probe == "can_execute":
                probe_entered.set()
                release_probe.wait()
                return True
            return False

        def health(self) -> dict[str, Any]:
            if blocked_probe == "health":
                probe_entered.set()
                release_probe.wait()
            return {"checked": True, "ok": True, "status": "healthy"}

    registry = provider_module.DesktopExecutionProviderRegistry(
        [BlockingAdapter()]
    )
    route = _background_tool_request()["desktop_execution_route"]
    request = _background_tool_request()

    def select_adapter() -> None:
        try:
            registry.adapter_for(
                CUA_BACKGROUND_PROVIDER_KIND,
                "desktop.safe_type_text",
                route,
                request,
            )
        except BaseException as exc:
            worker_errors.append(exc)

    worker = threading.Thread(target=select_adapter)
    worker.start()
    assert probe_entered.wait(2)

    # Use a non-blocking acquisition instead of a timing threshold: while the
    # provider probe is deliberately suspended, another register operation
    # must be able to take the registry lock immediately.
    lock_acquired = registry._lock.acquire(blocking=False)
    try:
        if lock_acquired:
            registry.register(_FakeBackgroundAdapter())
    finally:
        if lock_acquired:
            registry._lock.release()
        release_probe.set()
        worker.join(2)

    assert lock_acquired is True
    assert not worker.is_alive()
    assert worker_errors == []
    assert len(registry._adapters[CUA_BACKGROUND_PROVIDER_KIND]) == 2


def test_registry_replacement_does_not_close_adapter_already_selected_for_execution(
    monkeypatch,
) -> None:
    selected_event = threading.Event()
    continue_event = threading.Event()
    errors: list[BaseException] = []

    class StatefulAdapter(_FakeBackgroundAdapter):
        def __init__(self) -> None:
            self.unhealthy = False
            self.closed = False

        def can_execute(
            self,
            tool_name: str,
            route: Mapping[str, Any],
            tool_request: Mapping[str, Any],
        ) -> bool:
            del tool_name, route, tool_request
            return not self.unhealthy

        def health(self) -> dict[str, Any]:
            return {
                "checked": True,
                "ok": not self.unhealthy,
                "status": "unreachable" if self.unhealthy else "healthy",
                "blocking_conditions": (
                    ["desktop_execution_provider_unreachable"]
                    if self.unhealthy
                    else []
                ),
            }

        def close(self) -> None:
            self.closed = True

        def execute(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            del args, kwargs
            if self.closed:
                raise AssertionError("selected adapter was closed before execution")
            return {"ok": True}

    stale = StatefulAdapter()
    healthy = _FakeBackgroundAdapter()
    monkeypatch.setattr(
        provider_module,
        "cua_background_provider_adapter_from_env",
        lambda *_args, **_kwargs: healthy,
    )
    registry = provider_module.DesktopExecutionProviderRegistry([stale])
    route = _background_tool_request()["desktop_execution_route"]
    request = _background_tool_request()

    def select_then_execute() -> None:
        try:
            selected = registry.adapter_for(
                CUA_BACKGROUND_PROVIDER_KIND,
                "desktop.safe_type_text",
                route,
                request,
            )
            assert selected is stale
            selected_event.set()
            assert continue_event.wait(2)
            selected.execute(
                "desktop.safe_type_text",
                {"text": "hello"},
                tool_request=request,
                route=route,
                broker=object(),
            )
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=select_then_execute)
    worker.start()
    assert selected_event.wait(2)

    stale.unhealthy = True
    replacement = registry.adapter_for(
        CUA_BACKGROUND_PROVIDER_KIND,
        "desktop.safe_type_text",
        route,
        request,
    )
    assert replacement is healthy
    assert stale.closed is False

    continue_event.set()
    worker.join(2)
    assert not worker.is_alive()
    assert errors == []

    registry.close()
    assert stale.closed is True


def test_background_status_routes_without_virtual_desktop_claims(monkeypatch) -> None:
    monkeypatch.setattr(
        policy_module,
        "cua_background_provider_status",
        lambda **_kwargs: {
            "configured": True,
            "available": True,
            "adapter_ready": True,
            "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
            "provider_id": "cua-driver",
            "status": "available",
            "source": "cua_mcp_electron_bridge",
            "blocking_conditions": [],
            "supported_tools": ["desktop.safe_type_text"],
            "foreground_mutation_supported": True,
            "keyboard_mouse_capture_supported": True,
            "desktop_session_kind": "background_desktop",
            "desktop_session_isolated": False,
            "foreground_takeover_required": False,
            "desktop_backend_kind": "cua_driver",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": False,
            "requires_real_virtual_desktop_backend": False,
            "health": {
                "ok": False,
                "checked": False,
                "status": "not_checked",
                "blocking_conditions": [],
                "supported_tools": ["desktop.safe_type_text"],
                "capabilities": ["background_input"],
            },
        },
    )
    policy = policy_module.daily_entrypoint_desktop_execution_policy(surface="chat")

    route = policy_module.desktop_execution_route_decision(
        "desktop.safe_type_text",
        policy=policy,
        execution_mode=DesktopExecutionModeSnapshot(
            mode="supervised_live",
            foreground_control=True,
            keyboard_mouse_capture=True,
        ),
        metadata={},
    )
    status = policy_module.sandbox_desktop_provider_status(policy)

    assert route["status"] == "provider_ready"
    assert route["can_execute"] is True
    assert route["sandbox_required"] is False
    assert route["background_desktop_preferred"] is True
    assert route["isolated_desktop_preferred"] is False
    assert route["requires_user_foreground_session"] is False
    assert status["provider_kind"] == CUA_BACKGROUND_PROVIDER_KIND
    assert status["source"] == "cua_mcp_electron_bridge"
    assert status["provider_contract"] == {}
    assert status["desktop_session_isolated"] is False


def test_explicit_execution_route_probe_checks_background_provider_health(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_background_status(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        probe_health = bool(kwargs.get("probe_health"))
        calls.append(probe_health)
        if probe_health:
            return {
                "available": True,
                "adapter_ready": True,
                "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
                "provider_id": "cua-driver",
                "status": "available",
                "supported_tools": ["app.open"],
                "desktop_session_kind": "background_desktop",
                "desktop_session_isolated": False,
                "foreground_takeover_required": False,
                "desktop_backend_kind": "cua_driver",
                "desktop_backend_is_loopback": False,
                "desktop_backend_ready_for_public_release": True,
                "requires_real_virtual_desktop_backend": False,
                "health": {
                    "ok": True,
                    "checked": True,
                    "status": "healthy",
                    "blocking_conditions": [],
                    "supported_tools": ["app.open"],
                    "capabilities": ["background_input"],
                },
            }
        return {
            "available": False,
            "adapter_ready": False,
            "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
            "provider_id": "cua-driver",
            "status": "installed_not_checked",
            "supported_tools": ["app.open"],
            "desktop_session_kind": "background_desktop",
            "desktop_session_isolated": False,
            "foreground_takeover_required": False,
            "desktop_backend_kind": "cua_driver",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": False,
            "requires_real_virtual_desktop_backend": False,
            "health": {
                "ok": False,
                "checked": False,
                "status": "not_checked",
                "blocking_conditions": [],
                "supported_tools": ["app.open"],
                "capabilities": ["background_input"],
            },
        }

    monkeypatch.setattr(
        policy_module,
        "cua_background_provider_status",
        fake_background_status,
    )

    route = policy_module.desktop_execution_route_decision(
        "app.open",
        policy=policy_module.daily_entrypoint_desktop_execution_policy(surface="chat"),
        execution_mode=DesktopExecutionModeSnapshot(
            mode="supervised_live",
            foreground_control=True,
            keyboard_mouse_capture=False,
        ),
        metadata={"desktop_provider_health_probe": True},
    )

    assert calls == [True]
    assert route["status"] == "provider_ready"
    assert route["can_execute"] is True
    assert route["selected_provider_kind"] == CUA_BACKGROUND_PROVIDER_KIND
    assert route["selected_provider_id"] == "cua-driver"


def test_passive_background_route_exposes_deferred_provider_readiness(monkeypatch) -> None:
    """Planning must preserve why a configured provider is not executable yet."""

    monkeypatch.setattr(
        policy_module,
        "cua_background_provider_status",
        lambda **_kwargs: {
            "configured": True,
            "available": False,
            "adapter_ready": False,
            "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
            "provider_id": "cua-driver",
            "status": "installed_not_checked",
            "source": "cua_mcp_electron_bridge",
            "blocking_conditions": [],
            "supported_tools": ["desktop.list_apps"],
            "foreground_mutation_supported": True,
            "keyboard_mouse_capture_supported": True,
            "desktop_session_kind": "background_desktop",
            "desktop_session_isolated": False,
            "foreground_takeover_required": False,
            "desktop_backend_kind": "cua_driver",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": False,
            "requires_real_virtual_desktop_backend": False,
            "health": {
                "ok": False,
                "checked": False,
                "status": "not_checked",
                "blocking_conditions": [],
                "supported_tools": ["desktop.list_apps"],
                "capabilities": ["background_input"],
            },
        },
    )

    route = policy_module.desktop_execution_route_decision(
        "desktop.list_apps",
        policy=policy_module.daily_entrypoint_desktop_execution_policy(surface="chat"),
        execution_mode=DesktopExecutionModeSnapshot(
            mode="tool_native",
            foreground_control=False,
            keyboard_mouse_capture=False,
        ),
        metadata={"desktop_provider_route_readonly": True},
    )

    assert route["status"] == "provider_required"
    assert route["can_execute"] is False
    assert route["selected_provider_kind"] == CUA_BACKGROUND_PROVIDER_KIND
    assert route["provider_readiness_status"] == "installed_not_checked"
    assert route["blocking_conditions"] == ["sandbox_desktop_provider_required"]
