"""AgentStudioService start-entrypoint planner event regressions."""

from __future__ import annotations

from typing import Any

from apps.shell.yachiyo_agent import AgentStudioService
from tests.test_yachiyo_agent_service import _install_fake_isolated_provider_session


def test_studio_start_agent_run_enriches_bare_port_payload_with_planner_events() -> None:
    port = _BareStartPort()
    run = AgentStudioService(port).start_agent_run(
        {
            "agent_id": "agent-1",
            "objective": "请分析 data/sales.csv 并输出报告",
        }
    )

    assert run.run_id == "agent-run-1"
    assert [event.event_type for event in run.events[:4]] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.plan.step",
    ]
    event_types = [event.event_type for event in run.events]
    assert "agent.task.todo.updated" in event_types
    assert "agent.task.checkpoint.updated" in event_types
    assert run.task_core is not None
    assert run.task_core.todos
    assert run.events[0].payload["intent"]["kind"] == "data_analysis"
    start_payload = port.agent_run_payloads[0]
    assert "runtime_execution_envelope" in start_payload
    assert [request["tool"] for request in start_payload["direct_tool_requests"]] == [
        "workspace.read",
        "data.analyze",
    ]
    assert [request["step_id"] for request in start_payload["direct_tool_requests"]] == [
        "read-data-source",
        "analyze-data-file",
    ]
    assert run.task_core is not None
    assert [todo.step_id for todo in run.task_core.todos] == [
        "read-data-source",
        "analyze-data-file",
    ]


def test_studio_start_agent_run_routes_media_query_through_desktop_fallback(
    monkeypatch,
) -> None:
    _clear_desktop_provider_env(monkeypatch)
    _install_fake_isolated_provider_session(monkeypatch)
    port = _BareStartPort()
    run = AgentStudioService(port).start_agent_run(
        {
            "agent_id": "agent-1",
            "objective": "用 Apple Music 播放超时空辉夜姬",
            "allowed_tools": [
                "desktop.list_apps",
                "app.open",
                "desktop.safe_shortcut",
                "desktop.type",
                "desktop.safe_key",
                "desktop.click_ui_element",
                "desktop.ui_elements",
            ],
        }
    )

    start_payload = port.agent_run_payloads[0]
    tools = [request["tool"] for request in start_payload["direct_tool_requests"]]
    assert tools == [
        "desktop.list_apps",
        "app.open",
        "desktop.safe_shortcut",
        "desktop.type",
        "desktop.safe_key",
        "desktop.click_ui_element",
        "desktop.ui_elements",
    ]
    assert start_payload["direct_tool_requests"][0]["step_id"] == "discover-media-app"
    assert start_payload["direct_tool_requests"][3]["input"] == {"text": "超时空辉夜姬"}
    assert start_payload["direct_tool_requests"][4]["input"] == {
        "key": "return",
        "modifiers": [],
    }
    assert start_payload["metadata"]["yachiyo_execution_requests"] == tools
    assert run.task_core is not None
    assert [todo.step_id for todo in run.task_core.todos] == [
        "discover-media-app",
        "open-media-app",
        "focus-media-app-search",
        "type-media-search-query",
        "submit-media-search",
        "play-media-search-result",
        "verify-media-search",
    ]


def test_studio_start_entrypoints_auto_start_isolated_desktop_provider(
    monkeypatch,
) -> None:
    _clear_desktop_provider_env(monkeypatch)
    start_calls = _install_fake_isolated_provider_session(monkeypatch)
    service_port = _BareStartPort()
    service = AgentStudioService(service_port)
    request_payload = {
        "objective": "打开 PixelForge",
        "allowed_tools": ["desktop.list_apps", "app.open", "desktop.active_window"],
    }

    agent_run = service.start_agent_run({"agent_id": "agent-1", **request_payload})
    _clear_desktop_provider_env(monkeypatch)
    group_run = service.start_group_run({"group_id": "group-1", **request_payload})
    _clear_desktop_provider_env(monkeypatch)
    workflow_run = service.start_workflow_run(
        {"workflow_id": "workflow-1", **request_payload}
    )

    assert start_calls == [
        _real_virtual_backend_start_call(),
        _real_virtual_backend_start_call(),
        _real_virtual_backend_start_call(),
    ]
    _assert_start_payload_uses_isolated_session(service_port.agent_run_payloads[0])
    _assert_start_payload_uses_isolated_session(
        service_port.group_run_payloads[0],
        context_key="group_id",
        context_value="group-1",
    )
    _assert_start_payload_uses_isolated_session(
        service_port.workflow_run_payloads[0],
        context_key="workflow_id",
        context_value="workflow-1",
    )
    _assert_plan_event_uses_isolated_session(agent_run.events, "agent.plan.created")
    _assert_provider_session_event(
        agent_run.events,
        context_key="",
        context_value="",
    )
    _assert_plan_event_uses_isolated_session(
        group_run.events,
        "group.run.plan.created",
        context_key="group_run_id",
        context_value="group-run-1",
    )
    _assert_provider_session_event(
        group_run.events,
        context_key="group_run_id",
        context_value="group-run-1",
    )
    _assert_plan_event_uses_isolated_session(
        workflow_run.events,
        "workflow.run.plan.created",
        context_key="workflow_run_id",
        context_value="workflow-run-1",
    )
    _assert_provider_session_event(
        workflow_run.events,
        context_key="workflow_run_id",
        context_value="workflow-run-1",
    )


def test_studio_start_group_run_enriches_bare_port_payload_with_group_scoped_events() -> None:
    port = _BareStartPort()
    group_run = AgentStudioService(port).start_group_run(
        {
            "group_id": "group-1",
            "objective": "请两位 agent 对比方案并产出总结",
        }
    )

    event_types = [event.event_type for event in group_run.events]

    assert group_run.group_run_id == "group-run-1"
    assert "group.run.started" in event_types
    assert "group.run.intent.selected" in event_types
    assert "group.run.plan.created" in event_types
    assert "group.run.task_core.created" in event_types
    assert "group.run.task.todo.updated" in event_types
    assert "group.run.task.checkpoint.updated" in event_types
    assert group_run.task_core is not None
    assert group_run.task_core.todos
    start_payload = port.group_run_payloads[0]
    request_envelope = start_payload["metadata"]["yachiyo_execution_envelope"]
    assert request_envelope["requests"][0]["group_id"] == "group-1"
    assert start_payload["direct_tool_requests"][0]["group_id"] == "group-1"
    plan_event = next(event for event in group_run.events if event.event_type == "group.run.plan.created")
    event_request = plan_event.payload["runtime_execution_envelope"]["requests"][0]
    assert event_request["group_id"] == "group-1"
    assert event_request["group_run_id"] == "group-run-1"
    assert event_request["run_group_id"] == "group-run-1"


def test_studio_start_group_run_scopes_media_desktop_fallback_requests() -> None:
    port = _BareStartPort()
    group_run = AgentStudioService(port).start_group_run(
        {
            "group_id": "group-1",
            "objective": "用 Apple Music 播放超时空辉夜姬",
            "allowed_tools": [
                "desktop.list_apps",
                "app.open",
                "desktop.safe_shortcut",
                "desktop.type",
                "desktop.safe_key",
                "desktop.click_ui_element",
                "desktop.ui_elements",
            ],
        }
    )

    start_payload = port.group_run_payloads[0]
    tools = [request["tool"] for request in start_payload["direct_tool_requests"]]
    assert tools == [
        "desktop.list_apps",
        "app.open",
        "desktop.safe_shortcut",
        "desktop.type",
        "desktop.safe_key",
        "desktop.click_ui_element",
        "desktop.ui_elements",
    ]
    assert {
        request.get("group_id")
        for request in start_payload["direct_tool_requests"]
    } == {"group-1"}
    assert {
        request.get("group_run_id")
        for request in start_payload["direct_tool_requests"]
    } == {None}
    assert group_run.task_core is not None
    assert [todo.step_id for todo in group_run.task_core.todos] == [
        "discover-media-app",
        "open-media-app",
        "focus-media-app-search",
        "type-media-search-query",
        "submit-media-search",
        "play-media-search-result",
        "verify-media-search",
    ]
    plan_event = next(event for event in group_run.events if event.event_type == "group.run.plan.created")
    event_request = plan_event.payload["runtime_execution_envelope"]["requests"][0]
    assert event_request["group_id"] == "group-1"
    assert event_request["group_run_id"] == "group-run-1"


def test_studio_start_workflow_run_enriches_bare_port_payload_with_workflow_scoped_events() -> None:
    port = _BareStartPort()
    workflow_run = AgentStudioService(port).start_workflow_run(
        {
            "workflow_id": "workflow-1",
            "objective": "打开 PixelForge",
        }
    )

    event_types = [event.event_type for event in workflow_run.events]

    assert workflow_run.workflow_run_id == "workflow-run-1"
    assert "workflow.run.started" in event_types
    assert "workflow.run.intent.selected" in event_types
    assert "workflow.run.plan.created" in event_types
    assert "workflow.run.task_core.created" in event_types
    assert "workflow.run.task.todo.updated" in event_types
    assert "workflow.run.task.checkpoint.updated" in event_types
    assert workflow_run.task_core is not None
    assert workflow_run.task_core.todos
    start_payload = port.workflow_run_payloads[0]
    request_envelope = start_payload["metadata"]["yachiyo_execution_envelope"]
    assert request_envelope["requests"][0]["workflow_id"] == "workflow-1"
    assert start_payload["direct_tool_requests"][0]["workflow_id"] == "workflow-1"
    plan_event = next(
        event for event in workflow_run.events if event.event_type == "workflow.run.plan.created"
    )
    event_request = plan_event.payload["runtime_execution_envelope"]["requests"][0]
    assert event_request["workflow_id"] == "workflow-1"
    assert event_request["workflow_run_id"] == "workflow-run-1"


def test_studio_start_workflow_run_scopes_media_desktop_fallback_requests() -> None:
    port = _BareStartPort()
    workflow_run = AgentStudioService(port).start_workflow_run(
        {
            "workflow_id": "workflow-1",
            "objective": "用 Apple Music 播放超时空辉夜姬",
            "allowed_tools": [
                "desktop.list_apps",
                "app.open",
                "desktop.safe_shortcut",
                "desktop.type",
                "desktop.safe_key",
                "desktop.click_ui_element",
                "desktop.ui_elements",
            ],
        }
    )

    start_payload = port.workflow_run_payloads[0]
    tools = [request["tool"] for request in start_payload["direct_tool_requests"]]
    assert tools == [
        "desktop.list_apps",
        "app.open",
        "desktop.safe_shortcut",
        "desktop.type",
        "desktop.safe_key",
        "desktop.click_ui_element",
        "desktop.ui_elements",
    ]
    assert {
        request.get("workflow_id")
        for request in start_payload["direct_tool_requests"]
    } == {"workflow-1"}
    assert {
        request.get("workflow_run_id")
        for request in start_payload["direct_tool_requests"]
    } == {None}
    assert workflow_run.task_core is not None
    assert [todo.step_id for todo in workflow_run.task_core.todos] == [
        "discover-media-app",
        "open-media-app",
        "focus-media-app-search",
        "type-media-search-query",
        "submit-media-search",
        "play-media-search-result",
        "verify-media-search",
    ]
    plan_event = next(
        event for event in workflow_run.events if event.event_type == "workflow.run.plan.created"
    )
    event_request = plan_event.payload["runtime_execution_envelope"]["requests"][0]
    assert event_request["workflow_id"] == "workflow-1"
    assert event_request["workflow_run_id"] == "workflow-run-1"


def test_studio_start_agent_run_does_not_duplicate_existing_planner_events() -> None:
    run = AgentStudioService(_BareStartPort(existing_planner_events=True)).start_agent_run(
        {
            "agent_id": "agent-1",
            "objective": "请分析 data/sales.csv 并输出报告",
        }
    )

    assert [event.event_type for event in run.events].count("agent.intent.selected") == 1


class _BareStartPort:
    def __init__(self, *, existing_planner_events: bool = False) -> None:
        self.existing_planner_events = existing_planner_events
        self.agent_run_payloads: list[dict[str, Any]] = []
        self.group_run_payloads: list[dict[str, Any]] = []
        self.workflow_run_payloads: list[dict[str, Any]] = []

    def start_agent_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.agent_run_payloads.append(payload)
        events = []
        if self.existing_planner_events:
            events.append(
                {
                    "event_type": "agent.intent.selected",
                    "payload": {"intent": {"kind": "data_analysis"}},
                }
            )
        return {
            "run_id": "agent-run-1",
            "agent_id": payload.get("agent_id") or "agent-1",
            "title": payload.get("title") or "Agent run",
            "status": "running",
            "events": events,
        }

    def start_group_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.group_run_payloads.append(payload)
        return {
            "group_run_id": "group-run-1",
            "run_group_id": "group-run-1",
            "group_id": payload.get("group_id") or "group-1",
            "title": payload.get("title") or "Group run",
            "objective": payload.get("objective") or "",
            "status": "running",
            "events": [],
            "participants": [],
            "runs": [],
            "child_run_ids": [],
        }

    def start_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.workflow_run_payloads.append(payload)
        return {
            "run_id": "workflow-run-1",
            "workflow_run_id": "workflow-run-1",
            "workflow_id": payload.get("workflow_id") or "workflow-1",
            "title": payload.get("title") or "Workflow run",
            "objective": payload.get("objective") or "",
            "status": "running",
            "events": [],
        }


def _clear_desktop_provider_env(monkeypatch: Any) -> None:
    for key in (
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
    ):
        monkeypatch.delenv(key, raising=False)


def _assert_start_payload_uses_isolated_session(
    payload: dict[str, Any],
    *,
    context_key: str = "",
    context_value: str = "",
) -> None:
    envelope = payload["runtime_execution_envelope"]
    session = envelope["desktop_provider_session"]
    assert session["needed"] is True
    assert session["started"] is True
    assert session["running"] is True
    assert session["provider_id"] == "local-isolated-desktop"
    assert session["desktop_session_kind"] == "isolated_desktop"
    assert session["desktop_session_isolated"] is True
    assert session["foreground_takeover_required"] is False
    assert session["keyboard_mouse_capture_supported"] is True
    assert session["requires_real_virtual_desktop_backend"] is True
    assert session["tool_names"] == [
        "app.open",
        "desktop.active_window",
        "desktop.list_apps",
    ]
    assert [request["tool"] for request in payload["direct_tool_requests"]] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert {
        request["desktop_provider_session"]["provider_id"]
        for request in payload["direct_tool_requests"]
    } == {"local-isolated-desktop"}
    assert payload["direct_tool_requests"][1]["desktop_execution_route"]["status"] == (
        "sandbox_ready"
    )
    if context_key:
        assert {request.get(context_key) for request in payload["direct_tool_requests"]} == {
            context_value
        }


def _assert_plan_event_uses_isolated_session(
    events: list[Any],
    event_type: str,
    *,
    context_key: str = "",
    context_value: str = "",
) -> None:
    plan_event = next(event for event in events if event.event_type == event_type)
    envelope = plan_event.payload["runtime_execution_envelope"]
    session = envelope["desktop_provider_session"]
    assert session["needed"] is True
    assert session["running"] is True
    assert session["provider_id"] == "local-isolated-desktop"
    assert session["desktop_session_kind"] == "isolated_desktop"
    assert session["requires_real_virtual_desktop_backend"] is True
    assert envelope["requests"][1]["desktop_provider_session"]["provider_id"] == (
        "local-isolated-desktop"
    )
    if context_key:
        assert envelope["requests"][0][context_key] == context_value


def _assert_provider_session_event(
    events: list[Any],
    *,
    context_key: str,
    context_value: str,
) -> None:
    provider_event = next(
        event
        for event in events
        if event.event_type == "desktop.provider_session.started"
    )
    session = provider_event.payload["desktop_provider_session"]
    assert session["provider_id"] == "local-isolated-desktop"
    assert session["started"] is True
    assert session["running"] is True
    assert session["needed"] is True
    assert session["desktop_execution_session_mode"] == "isolated_desktop"
    assert session["desktop_execution_session_label"] == "isolated desktop provider"
    assert session["desktop_session_kind"] == "isolated_desktop"
    assert session["desktop_session_isolated"] is True
    assert session["foreground_takeover_required"] is False
    assert session["keyboard_mouse_capture_supported"] is True
    assert session["requires_real_virtual_desktop_backend"] is True
    assert session["tool_names"] == [
        "app.open",
        "desktop.active_window",
        "desktop.list_apps",
    ]
    assert "env" not in session
    assert "command" not in session
    if context_key:
        assert provider_event.payload[context_key] == context_value


def _real_virtual_backend_start_call() -> dict[str, Any]:
    return {
        "tools": ["app.open", "desktop.active_window", "desktop.list_apps"],
        "requires_real_virtual_desktop_backend": True,
    }
