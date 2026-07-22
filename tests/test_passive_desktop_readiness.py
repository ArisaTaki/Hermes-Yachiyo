from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from apps.shell import chat_api
from apps.shell.agent.runtime.desktop_execution_providers import (
    LOCAL_DESKTOP_PROVIDER_ID,
    LocalDesktopExecutionProviderAdapter,
)
from apps.shell.agent.tools import desktop as desktop_tools
from apps.shell.agent.tools import registry as tool_registry
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.policy import RuntimePolicyCompiler
from apps.shell.yachiyo_agent import desktop_permissions, legacy_ports, legacy_tasks
from apps.shell.yachiyo_agent.legacy_ports import LegacyStudioPort
from apps.shell.yachiyo_agent.legacy_tasks import LegacyRuntimePort
from apps.shell.yachiyo_agent.policy import desktop_tool_execution_mode_for_input


def _install_passive_probe_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    active_calls: list[str] = []

    def active_permission_probe(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        active_calls.append("permissions")
        return {}

    def active_blocker_probe(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        active_calls.append("runtime_blockers")
        return {}

    monkeypatch.setattr(
        desktop_permissions,
        "desktop_permission_missing_by_capability",
        active_permission_probe,
    )
    monkeypatch.setattr(
        desktop_permissions,
        "desktop_runtime_blocking_conditions_by_capability",
        active_blocker_probe,
    )
    monkeypatch.setattr(
        desktop_tools,
        "_run_osascript",
        lambda *_args, **_kwargs: active_calls.append("osascript") or {"ok": True},
    )
    monkeypatch.setattr(
        legacy_ports,
        "local_desktop_execution_runtime_probe",
        lambda: active_calls.append("local_runtime_probe") or {},
        raising=False,
    )
    return active_calls


def test_automatic_readiness_catalog_and_planner_warmup_never_run_active_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop_permissions.clear_desktop_permission_probe_cache()
    active_calls = _install_passive_probe_guards(monkeypatch)
    monkeypatch.setattr(
        legacy_tasks,
        "sandbox_desktop_provider_status",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        legacy_ports,
        "sandbox_desktop_provider_status",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        legacy_ports,
        "controlled_desktop_provider_diagnostics_payload",
        lambda **_kwargs: {},
    )
    runtime_port = LegacyRuntimePort(
        SimpleNamespace(list_runnables=lambda: {"runnables": []})
    )
    studio_port = LegacyStudioPort(
        SimpleNamespace(list_restricted_tool_plugins=lambda: {"plugins": []})
    )

    # These endpoints are polled repeatedly in Launcher and Tool Center. Repeated
    # calls must stay passive even after an underlying probe cache would expire.
    for _ in range(3):
        readiness = runtime_port.readiness()
        catalog = studio_port.list_tool_catalog()
        assert readiness["ok"] is True
        assert "tools" in catalog
        assert readiness["capabilities"]["desktop_permission_diagnostics"] == {
            "checked": False,
            "status": "not_checked",
        }
        assert readiness["capabilities"]["desktop_execution"]["available"] is False
        assert readiness["capabilities"]["desktop_execution"][
            "blocking_conditions"
        ] == ["desktop_permission_diagnostics_not_checked"]
        assert catalog["capabilities"]["desktop_execution"]["available"] is False
        chat_api.ChatAPI._warm_daily_desktop_permission_cache(
            object(),
            [{"tool": "desktop.inspect_app", "input": {"app_name": "Music"}}],
        )

    assert active_calls == []


def test_desktop_permissions_default_is_passive_unknown_without_apple_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop_permissions.clear_desktop_permission_probe_cache()
    active_calls: list[str] = []
    monkeypatch.setattr(
        desktop_permissions,
        "desktop_permission_missing_by_capability",
        lambda **_kwargs: active_calls.append("permissions") or {},
    )
    monkeypatch.setattr(
        desktop_permissions,
        "desktop_runtime_blocking_conditions_by_capability",
        lambda **_kwargs: active_calls.append("runtime_blockers") or {},
    )
    monkeypatch.setattr(
        desktop_tools,
        "_run_osascript",
        lambda *_args, **_kwargs: active_calls.append("osascript") or {"ok": True},
    )

    for _ in range(3):
        result = desktop_tools.permissions()
        assert result["ok"] is True
        assert result["action"] == "desktop.permissions"
        assert result["checked"] is False
        assert result["data"]["ready"] is False
        assert result["diagnostic_status"] == "not_checked"
        assert result["blocking_conditions"] == [
            "desktop_permission_diagnostics_not_checked"
        ]
        assert result["recovery_actions"] == [
            {
                "label": "经你确认后验证桌面权限",
                "tool": "desktop.permissions.verify",
                "input": {},
                "permission_target": "desktop_permission_diagnostics",
                "risk_level": "medium",
            }
        ]

    assert active_calls == []


def test_interactive_permission_verification_requires_explicit_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        desktop_tools,
        "permissions",
        lambda *, active_verification=False: calls.append(active_verification)
        or {"ok": True, "action": "desktop.permissions"},
    )
    broker = ToolBroker(
        {"default_workdir": str(tmp_path), "readable_scopes": ["."]},
        tmp_path / "artifacts",
        approvals={"desktop.permissions.verify": True},
    )
    unconfigured_broker = ToolBroker(
        {"default_workdir": str(tmp_path), "readable_scopes": ["."]},
        tmp_path / "unconfigured-artifacts",
    )

    blocked = broker.call("desktop.permissions.verify", {}, approved=False)
    blocked_without_compiled_policy = unconfigured_broker.call(
        "desktop.permissions.verify",
        {},
        approved=False,
    )
    verified = broker.call("desktop.permissions.verify", {}, approved=True)
    policy = RuntimePolicyCompiler.default_tool_policy("custom")

    assert blocked["approval_required"] is True
    assert blocked_without_compiled_policy["approval_required"] is True
    assert calls == [True]
    assert verified["ok"] is True
    assert verified["action"] == "desktop.permissions.verify"
    assert policy["approval_required"]["desktop.permissions.verify"] is True


def test_desktop_inspect_app_defaults_to_passive_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutation_calls: list[str] = []
    monkeypatch.setattr(desktop_tools, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_tools,
        "list_apps",
        lambda **_kwargs: {
            "ok": True,
            "data": {"apps": [{"name": "Music"}]},
        },
    )
    monkeypatch.setattr(
        desktop_tools,
        "app_status",
        lambda _app_name: {"ok": True, "data": {"running": False}},
    )
    monkeypatch.setattr(
        desktop_tools,
        "app_open",
        lambda _app_name: mutation_calls.append("open") or {"ok": True},
    )
    monkeypatch.setattr(
        desktop_tools,
        "app_focus",
        lambda _app_name: mutation_calls.append("focus") or {"ok": True},
    )
    monkeypatch.setattr(
        desktop_tools,
        "active_window",
        lambda: mutation_calls.append("active_window") or {"ok": True},
    )
    monkeypatch.setattr(
        desktop_tools,
        "windows",
        lambda _app_name="": {"ok": True, "data": {"windows": [], "count": 0}},
    )
    monkeypatch.setattr(
        desktop_tools,
        "ui_elements",
        lambda **_kwargs: {
            "ok": True,
            "data": {"elements": [], "count": 0, "control_like_count": 0},
        },
    )

    result = desktop_tools.inspect_app("Music")

    assert result["ok"] is True
    assert result["data"]["open_if_needed"] is False
    assert result["data"]["focus_requested"] is False
    assert mutation_calls == []


def test_inspect_app_defaults_are_passive_across_registry_and_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatched: list[tuple[bool, bool]] = []

    class FakeBroker:
        def desktop_inspect_app(
            self,
            _app_name: str,
            *,
            open_if_needed: Any,
            focus: Any,
            role_filter: str,
            limit: Any,
        ) -> dict[str, Any]:
            del role_filter, limit
            dispatched.append((open_if_needed, focus))
            return {"ok": True, "action": "desktop.inspect_app"}

    tool_registry.TOOL_DISPATCH_REGISTRY["desktop.inspect_app"](
        FakeBroker(),
        {"app_name": "Music"},
        False,
    )

    monkeypatch.setattr(
        desktop_tools,
        "inspect_app",
        lambda _app_name, **kwargs: dispatched.append(
            (kwargs["open_if_needed"], kwargs["focus"])
        )
        or {"ok": True},
    )
    broker = ToolBroker(
        {"default_workdir": str(tmp_path), "readable_scopes": ["."]},
        tmp_path / "artifacts",
    )
    broker.desktop_inspect_app("Music")

    assert dispatched == [(False, False), (False, False)]


@pytest.mark.parametrize(
    "payload",
    [
        {"app_name": "Music", "open_if_needed": True, "focus": False},
        {"app_name": "Music", "open_if_needed": False, "focus": True},
    ],
)
def test_local_provider_rejects_mutating_inspect_without_foreground_authorization(
    payload: dict[str, Any],
) -> None:
    broker_calls: list[dict[str, Any]] = []

    class FakeBroker:
        def call(
            self,
            _tool_name: str,
            value: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            del approved
            broker_calls.append(value)
            return {"ok": True}

    adapter = LocalDesktopExecutionProviderAdapter()
    route = {"selected_provider_id": LOCAL_DESKTOP_PROVIDER_ID}
    request = {"tool": "desktop.inspect_app", "input": payload}

    assert adapter.can_execute("desktop.inspect_app", route, request) is False
    result = adapter.execute(
        "desktop.inspect_app",
        payload,
        tool_request=request,
        route=route,
        broker=FakeBroker(),
    )

    assert result["ok"] is False
    assert result["status"] == "local_desktop_foreground_not_authorized"
    assert broker_calls == []


def test_local_provider_allows_passive_inspect_without_foreground_authorization() -> None:
    broker_calls: list[dict[str, Any]] = []

    class FakeBroker:
        def call(
            self,
            _tool_name: str,
            value: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            del approved
            broker_calls.append(value)
            return {"ok": True, "action": "desktop.inspect_app"}

    adapter = LocalDesktopExecutionProviderAdapter()
    route = {"selected_provider_id": LOCAL_DESKTOP_PROVIDER_ID}
    payload = {"app_name": "Music"}
    request = {"tool": "desktop.inspect_app", "input": payload}

    assert adapter.can_execute("desktop.inspect_app", route, request) is True
    result = adapter.execute(
        "desktop.inspect_app",
        payload,
        tool_request=request,
        route=route,
        broker=FakeBroker(),
    )

    assert result["ok"] is True
    assert broker_calls == [payload]


def test_inspect_app_policy_defaults_passive_but_explicit_focus_is_foreground() -> None:
    passive = desktop_tool_execution_mode_for_input(
        "desktop.inspect_app",
        {"app_name": "Music"},
    )
    foreground = desktop_tool_execution_mode_for_input(
        "desktop.inspect_app",
        {"app_name": "Music", "focus": True},
    )

    assert passive.foreground_control is False
    assert passive.mode == "read_only_observation"
    assert foreground.foreground_control is True
    assert foreground.mode == "supervised_live"
