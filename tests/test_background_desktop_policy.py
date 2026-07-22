from __future__ import annotations

from apps.shell.yachiyo_agent import desktop_execution_policy as policy_module
from apps.shell.agent.runtime.desktop_execution_providers import (
    LOCAL_DESKTOP_PROVIDER_KIND,
)
from apps.shell.yachiyo_agent import DesktopExecutionModeSnapshot
from apps.shell.yachiyo_agent.desktop_execution_policy import (
    daily_entrypoint_desktop_execution_policy,
    desktop_execution_route_decision,
    with_daily_entrypoint_desktop_execution_policy,
)
from apps.shell.yachiyo_agent.policy import desktop_tool_execution_mode


def _foreground_input_mode() -> DesktopExecutionModeSnapshot:
    return DesktopExecutionModeSnapshot(
        mode="supervised_live",
        foreground_control=True,
        keyboard_mouse_capture=True,
    )


def _read_only_mode() -> DesktopExecutionModeSnapshot:
    return DesktopExecutionModeSnapshot(mode="read_only_observation")


def test_daily_policy_prefers_background_execution_without_live_takeover() -> None:
    policy = daily_entrypoint_desktop_execution_policy(surface="chat")

    assert policy["mode"] == "preview_input"
    assert policy["allow_live_foreground"] is False
    assert policy["prefer_background_desktop"] is True
    assert policy["avoid_user_foreground_takeover"] is True
    assert policy["require_sandbox_for_keyboard_mouse"] is False


def test_background_provider_can_type_without_an_isolated_session() -> None:
    provider = {
        "available": True,
        "adapter_ready": True,
        "provider_kind": "background_desktop",
        "provider_id": "cua-driver",
        "status": "available",
        "supported_tools": ["desktop.safe_type_text"],
        "foreground_mutation_supported": True,
        "keyboard_mouse_capture_supported": True,
        "desktop_session_kind": "background_desktop",
        "desktop_session_isolated": False,
        "foreground_takeover_required": False,
        "blocking_conditions": [],
    }

    route = desktop_execution_route_decision(
        "desktop.safe_type_text",
        policy=daily_entrypoint_desktop_execution_policy(surface="chat"),
        execution_mode=_foreground_input_mode(),
        metadata={"sandbox_desktop_provider": provider},
    )

    assert route["status"] == "provider_ready"
    assert route["can_execute"] is True
    assert route["provider_execution_required"] is True
    assert route["selected_provider_kind"] == "background_desktop"
    assert route["selected_provider_id"] == "cua-driver"
    assert route["background_desktop_preferred"] is True
    assert route["isolated_desktop_preferred"] is False
    assert route["desktop_session_isolated"] is False
    assert route["foreground_takeover_required"] is False
    assert route["requires_user_foreground_session"] is False
    assert route["foreground_takeover_allowed"] is False


def test_daily_readonly_verifier_stays_on_the_background_provider() -> None:
    provider = {
        "available": True,
        "adapter_ready": True,
        "provider_kind": "background_desktop",
        "provider_id": "cua-driver",
        "status": "available",
        "supported_tools": ["desktop.active_window", "desktop.read_ui"],
        "desktop_session_kind": "background_desktop",
        "desktop_session_isolated": False,
        "foreground_takeover_required": False,
        "blocking_conditions": [],
    }
    metadata = with_daily_entrypoint_desktop_execution_policy(
        {"sandbox_desktop_provider": provider},
        surface="chat",
    )

    for tool_name in ("desktop.active_window", "desktop.read_ui"):
        route = desktop_execution_route_decision(
            tool_name,
            policy=metadata["desktop_execution_policy"],
            execution_mode=_read_only_mode(),
            metadata=metadata,
        )

        assert route["can_execute"] is True
        assert route["provider_execution_required"] is True
        assert route["selected_provider_kind"] == "background_desktop"
        assert route["selected_provider_id"] == "cua-driver"
        assert route["requires_user_foreground_session"] is False
        assert route["fallback_mode"] != "supervised_live"


def test_partial_background_provider_defers_to_capable_isolated_provider(
    monkeypatch,
) -> None:
    background = {
        "available": True,
        "adapter_ready": True,
        "provider_kind": "background_desktop",
        "provider_id": "cua-driver",
        "status": "available",
        "supported_tools": ["app.open"],
        "desktop_session_kind": "background_desktop",
        "desktop_session_isolated": False,
        "foreground_takeover_required": False,
        "blocking_conditions": [],
    }
    isolated = {
        "available": True,
        "adapter_ready": True,
        "provider_kind": "sandbox_desktop",
        "provider_id": "isolated-provider",
        "status": "available",
        "supported_tools": ["desktop.read_ui"],
        "desktop_session_kind": "isolated_desktop",
        "desktop_session_isolated": True,
        "foreground_takeover_required": False,
        "blocking_conditions": [],
    }
    monkeypatch.setattr(
        policy_module,
        "_background_desktop_provider_payload",
        lambda *_args, **_kwargs: dict(background),
    )
    monkeypatch.setattr(
        policy_module,
        "_sandbox_provider_payload_from_env",
        lambda **_kwargs: dict(isolated),
    )
    monkeypatch.setattr(
        policy_module,
        "_sandbox_provider_payload_from_manifest",
        lambda **_kwargs: {},
    )
    metadata = with_daily_entrypoint_desktop_execution_policy(
        {"source": "chat"},
        surface="chat",
    )

    route = desktop_execution_route_decision(
        "desktop.read_ui",
        policy=metadata["desktop_execution_policy"],
        execution_mode=_read_only_mode(),
        metadata=metadata,
    )

    assert route["can_execute"] is True
    assert route["provider_execution_required"] is True
    assert route["selected_provider_kind"] == "sandbox_desktop"
    assert route["selected_provider_id"] == "isolated-provider"
    assert route["desktop_session_isolated"] is True
    assert route["requires_user_foreground_session"] is False


def test_partial_background_readonly_never_falls_through_to_local_desktop() -> None:
    provider = {
        "available": True,
        "adapter_ready": True,
        "provider_kind": "background_desktop",
        "provider_id": "cua-driver",
        "status": "available",
        "supported_tools": ["app.open"],
        "desktop_session_kind": "background_desktop",
        "desktop_session_isolated": False,
        "foreground_takeover_required": False,
        "blocking_conditions": [],
    }
    metadata = with_daily_entrypoint_desktop_execution_policy(
        {"sandbox_desktop_provider": provider},
        surface="chat",
    )

    route = desktop_execution_route_decision(
        "desktop.verify",
        policy=metadata["desktop_execution_policy"],
        execution_mode=_read_only_mode(),
        metadata=metadata,
    )

    assert route["can_execute"] is False
    assert route["selected_provider_kind"] == "background_desktop"
    assert route["selected_provider_id"] == "cua-driver"
    assert route["requires_user_foreground_session"] is False
    assert route["fallback_mode"] == "user_handoff"
    assert route["blocking_conditions"] == ["sandbox_tool_not_supported"]


def test_daily_policy_does_not_fall_back_to_local_foreground() -> None:
    metadata = with_daily_entrypoint_desktop_execution_policy(
        {"source": "chat"},
        surface="chat",
    )

    route = desktop_execution_route_decision(
        "desktop.safe_type_text",
        policy=metadata["desktop_execution_policy"],
        execution_mode=_foreground_input_mode(),
        metadata=metadata,
    )

    assert route["can_execute"] is False
    assert route["selected_provider_kind"] == "background_desktop"
    assert route["selected_provider_id"] == "cua-driver"
    assert route["sandbox_required"] is False
    assert route["requires_user_foreground_session"] is False
    assert route["foreground_takeover_allowed"] is False
    assert route["fallback_mode"] == "user_handoff"
    assert route["blocking_conditions"] == ["cua_driver_not_installed"]


def test_daily_quit_foreground_app_requires_background_provider() -> None:
    metadata = with_daily_entrypoint_desktop_execution_policy(
        {"source": "chat"},
        surface="chat",
    )

    route = desktop_execution_route_decision(
        "desktop.quit_app",
        policy=metadata["desktop_execution_policy"],
        execution_mode=desktop_tool_execution_mode("desktop.quit_app"),
        metadata=metadata,
    )

    assert route["can_execute"] is False
    assert route["status"] == "provider_required"
    assert route["selected_provider_kind"] == "background_desktop"
    assert route["selected_provider_id"] == "cua-driver"
    assert route["requires_user_foreground_session"] is False
    assert route["foreground_takeover_allowed"] is False
    assert route["fallback_mode"] == "user_handoff"
    assert route["blocking_conditions"] == ["cua_driver_not_installed"]


def test_explicit_foreground_permission_keeps_existing_local_path() -> None:
    metadata = with_daily_entrypoint_desktop_execution_policy(
        {"allow_user_foreground_takeover": True},
        surface="chat",
    )

    route = desktop_execution_route_decision(
        "desktop.safe_type_text",
        policy=metadata["desktop_execution_policy"],
        execution_mode=_foreground_input_mode(),
        metadata=metadata,
    )

    assert route["can_execute"] is True
    assert route["selected_provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert route["foreground_takeover_allowed"] is True
    assert route["requires_user_foreground_session"] is True
    assert route["blocking_conditions"] == []


def test_non_background_provider_cannot_claim_same_session_safety() -> None:
    provider = {
        "available": True,
        "adapter_ready": True,
        "provider_kind": "sandbox_desktop",
        "provider_id": "mislabeled-provider",
        "status": "available",
        "supported_tools": ["desktop.safe_type_text"],
        "keyboard_mouse_capture_supported": True,
        "desktop_session_kind": "user_foreground",
        "desktop_session_isolated": False,
        "foreground_takeover_required": False,
        "blocking_conditions": [],
    }

    route = desktop_execution_route_decision(
        "desktop.safe_type_text",
        policy=daily_entrypoint_desktop_execution_policy(surface="chat"),
        execution_mode=_foreground_input_mode(),
        metadata={"sandbox_desktop_provider": provider},
    )

    assert route["can_execute"] is False
    assert route["status"] == "sandbox_desktop_session_required"
    assert route["blocking_conditions"] == ["sandbox_desktop_session_required"]
