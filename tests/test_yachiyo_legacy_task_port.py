"""Legacy Chat task runtime port adapter tests."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.yachiyo_agent.legacy_ports import (
    LegacyChatTaskStarter,
    LegacyRuntimePort as CompatLegacyRuntimePort,
)
from apps.shell.yachiyo_agent.legacy_tasks import LegacyRuntimePort
from apps.shell.yachiyo_agent.entrypoint_tool_selection import planner_first_direct_tool_selection


def test_legacy_runtime_port_starts_and_links_chat_task() -> None:
    runtime = _FakeRuntime()

    task = LegacyRuntimePort(runtime).start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    assert CompatLegacyRuntimePort is LegacyRuntimePort
    assert task["task_id"] == "task-1"
    assert task["conversation_id"] == "chat-1"
    assert task["open_in_studio_url"] == "#/agents?run_id=run-1"
    assert runtime.calls == [
        (
            "create_run_for_runnable_async",
            {"runnable_id": "builtin:yachiyo-main", "user_goal": "Patch README"},
        ),
        ("link_task_run", {"task_id": "task-1", "run_id": "run-1", "session_id": "chat-1"}),
        ("get_run", "run-1"),
    ]


def test_legacy_runtime_port_appends_runtime_planner_events_when_available() -> None:
    runtime = _PlannerEventFakeRuntime()

    task = LegacyRuntimePort(runtime).start_chat_task(
        {
            "prompt": "分析 sales.csv 并输出报告",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    planner_events = [call for call in runtime.calls if call[0] == "append_run_event"]
    assert task["task_id"] == "task-1"
    assert [event[1]["event_type"] for event in planner_events] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.plan.step",
    ]
    assert planner_events[0][1]["payload"]["intent"]["kind"] == "data_analysis"
    assert planner_events[1][1]["payload"]["plan"]["tool_plan"]["artifacts_expected"] == [
        "analysis-report.md",
    ]
    assert planner_events[2][1]["payload"]["step"]["tool_name"] == "data.analyze"


def test_legacy_runtime_port_appends_media_planner_events() -> None:
    runtime = _PlannerEventFakeRuntime()

    task = LegacyRuntimePort(runtime).start_chat_task(
        {
            "prompt": "能否帮我播放 Apple Music?",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    planner_events = [call for call in runtime.calls if call[0] == "append_run_event"]
    assert task["task_id"] == "task-1"
    assert [event[1]["event_type"] for event in planner_events] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.plan.step",
    ]
    assert planner_events[0][1]["payload"]["intent"]["kind"] == "media_playback"
    plan = planner_events[1][1]["payload"]["plan"]
    capabilities = {
        capability["capability_id"]: capability
        for capability in plan["capabilities"]
    }
    assert "media.playback" in capabilities
    assert plan["tool_plan"]["steps"][0]["tool_name"] == "media.apple_music_open_and_play"


def test_planner_first_direct_selection_owns_media_playback_without_legacy() -> None:
    def fail_legacy_requests(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("legacy media planner should not run for planner-owned playback")

    selection = planner_first_direct_tool_selection(
        "播放超时空辉夜姬",
        ["media.apple_music_play"],
        legacy_tool_requests=fail_legacy_requests,
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "media.apple_music_play",
            "input": {"query": "超时空辉夜姬"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_media_playback",
        },
    ]
    assert selection.event_payload["selection_source"] == "runtime_planner"
    assert selection.event_payload["legacy_request_count"] == 0
    assert selection.event_payload["selected_tools"] == ["media.apple_music_play"]


def test_planner_first_direct_selection_owns_clipboard_without_legacy() -> None:
    def fail_legacy_requests(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("legacy clipboard planner should not run for planner-owned clipboard")

    write_selection = planner_first_direct_tool_selection(
        "copy hello world to clipboard",
        ["clipboard.write"],
        legacy_tool_requests=fail_legacy_requests,
    )
    read_selection = planner_first_direct_tool_selection(
        "read selected text",
        ["desktop.safe_shortcut", "clipboard.read"],
        legacy_tool_requests=fail_legacy_requests,
    )

    assert write_selection.selected_source == "runtime_planner"
    assert write_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "clipboard.write",
            "input": {"text": "hello world"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_clipboard",
        },
    ]
    assert write_selection.event_payload["legacy_request_count"] == 0
    assert read_selection.selected_source == "runtime_planner"
    assert read_selection.event_payload["legacy_request_count"] == 0
    assert [request["tool"] for request in read_selection.requests] == [
        "desktop.safe_shortcut",
        "clipboard.read",
    ]


def test_planner_first_direct_selection_owns_system_control_without_legacy() -> None:
    def fail_legacy_requests(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("legacy system planner should not run for planner-owned system control")

    volume_selection = planner_first_direct_tool_selection(
        "音量调大",
        ["system.volume"],
        legacy_tool_requests=fail_legacy_requests,
    )
    screen_saver_selection = planner_first_direct_tool_selection(
        "打开屏保",
        ["system.screen_saver_start"],
        legacy_tool_requests=fail_legacy_requests,
    )

    assert volume_selection.selected_source == "runtime_planner"
    assert volume_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "system.volume",
            "input": {"action": "up"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_system_control",
        },
    ]
    assert volume_selection.event_payload["legacy_request_count"] == 0
    assert screen_saver_selection.selected_source == "runtime_planner"
    assert screen_saver_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "system.screen_saver_start",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_system_control",
        },
    ]
    assert screen_saver_selection.event_payload["legacy_request_count"] == 0


def test_planner_first_direct_selection_owns_web_research_without_legacy() -> None:
    def fail_legacy_requests(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("legacy browser planner should not run for planner-owned web research")

    selection = planner_first_direct_tool_selection(
        "open https://example.com",
        ["browser.open_url"],
        legacy_tool_requests=fail_legacy_requests,
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://example.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        },
    ]
    assert selection.event_payload["legacy_request_count"] == 0


def test_legacy_chat_task_starter_records_runtime_planner_metadata_and_events() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatPlannerEventRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)

    task = starter.execute_existing_main_chat_task(
        task_id="task-main",
        conversation_id="chat-1",
        prompt="打开 PixelForge",
    )

    assert task is not None
    assert task["task_id"] == "task-main"
    assert app_runtime.chat_session.metadata_calls[0]["metadata"]["yachiyo_runtime_planner"] is True
    assert app_runtime.chat_session.metadata_calls[0]["metadata"]["yachiyo_intent_kind"] == (
        "desktop_operation"
    )
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert metadata["daily_desktop_tool"] == "app.open"
    assert metadata["daily_desktop_tools"] == ["app.open"]
    assert metadata["daily_desktop_source"] == "runtime_planner"
    assert metadata["daily_desktop_planning_reason"] == "planner_fallback_desktop_operation"
    planner_events = [call for call in runtime.calls if call[0] == "append_run_event"]
    assert [event[1]["event_type"] for event in planner_events[:2]] == [
        "agent.intent.selected",
        "agent.plan.created",
    ]
    assert planner_events[0][1]["payload"]["intent"]["inputs"]["app_name_hint"] == "PixelForge"
    selection_events = [
        event for event in planner_events if event[1]["event_type"] == "agent.plan.selection"
    ]
    assert selection_events[0][1]["payload"]["selection_source"] == "runtime_planner"
    assert selection_events[0][1]["payload"]["selected_tools"] == ["app.open"]
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    assert [request["tool"] for request in model_loop_call[1]["direct_tool_requests"]] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]


def test_legacy_chat_task_starter_records_direct_selection_fallback_event() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatPlannerEventRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)

    task = starter.execute_existing_main_chat_task(
        task_id="task-github",
        conversation_id="chat-1",
        prompt="打开 GitHub",
    )

    assert task is not None
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert metadata["daily_desktop_source"] == "daily_desktop_intent"
    assert metadata["daily_desktop_tool"] == "browser.open_url"
    run_events = [call for call in runtime.calls if call[0] == "append_run_event"]
    assert [event[1]["event_type"] for event in run_events[:2]] == [
        "agent.intent.selected",
        "agent.plan.created",
    ]
    assert run_events[0][1]["payload"]["intent"]["kind"] == "desktop_operation"
    selection_events = [
        event for event in run_events if event[1]["event_type"] == "agent.plan.selection"
    ]
    assert selection_events[0][1]["payload"]["selection_source"] == "daily_desktop_intent"
    assert selection_events[0][1]["payload"]["selection_reason"] == "legacy_more_specific_direct_plan"
    assert selection_events[0][1]["payload"]["planner_tools"] == ["app.open"]
    assert selection_events[0][1]["payload"]["selected_tools"] == ["browser.open_url"]
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    assert model_loop_call[1]["direct_tool_requests"] == []


def test_legacy_chat_task_starter_keeps_migrated_context_prefetch_on_runtime_planner() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatPlannerEventRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)

    task = starter.execute_existing_main_chat_task(
        task_id="task-note-clipboard",
        conversation_id="chat-1",
        prompt="create a note from clipboard",
    )

    assert task is not None
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert metadata["daily_desktop_source"] == "runtime_planner"
    assert metadata["daily_desktop_tool"] == "clipboard.read"
    assert metadata["daily_desktop_planning_reason"] == (
        "planner_prefetch_information_capture_context"
    )
    selection_events = [
        event for event in runtime.calls if event[0] == "append_run_event"
        and event[1]["event_type"] == "agent.plan.selection"
    ]
    assert selection_events[0][1]["payload"]["selection_source"] == "runtime_planner"
    assert selection_events[0][1]["payload"]["legacy_request_count"] == 0
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    assert model_loop_call[1]["direct_tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_information_capture_context",
            "continue_to_model": True,
        }
    ]

    runtime.calls.clear()
    app_runtime.chat_session.metadata_calls.clear()
    task = starter.execute_existing_main_chat_task(
        task_id="task-send-link",
        conversation_id="chat-1",
        prompt="把当前网页链接发给微信文件传输助手",
    )

    assert task is not None
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert metadata["daily_desktop_source"] == "runtime_planner"
    assert metadata["daily_desktop_tool"] == "desktop.safe_shortcut"
    assert metadata["daily_desktop_tools"] == [
        "desktop.safe_shortcut",
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_shortcut",
        "desktop.submit_foreground",
    ]
    assert metadata["daily_desktop_planning_reason"] == "planner_fallback_communication_send"
    selection_events = [
        event for event in runtime.calls if event[0] == "append_run_event"
        and event[1]["event_type"] == "agent.plan.selection"
    ]
    assert selection_events[0][1]["payload"]["selection_source"] == "runtime_planner"
    assert selection_events[0][1]["payload"]["legacy_request_count"] == 0
    assert selection_events[0][1]["payload"]["selected_tools"] == [
        "desktop.safe_shortcut",
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_shortcut",
        "desktop.submit_foreground",
    ]
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_requests"] == []

    runtime.calls.clear()
    app_runtime.chat_session.metadata_calls.clear()
    task = starter.execute_existing_main_chat_task(
        task_id="task-open-clipboard-link",
        conversation_id="chat-1",
        prompt="open clipboard link",
    )

    assert task is not None
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert metadata["daily_desktop_source"] == "runtime_planner"
    assert metadata["daily_desktop_tool"] == "desktop.safe_shortcut"
    assert metadata["daily_desktop_tools"] == [
        "desktop.safe_shortcut",
        "desktop.safe_shortcut",
        "desktop.search_submit",
    ]
    assert metadata["daily_desktop_planning_reason"] == (
        "planner_fallback_dynamic_browser_context"
    )
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "focus_address_bar"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        }
    ]


def test_legacy_chat_task_starter_does_not_pass_full_plan_for_approval_tools() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatPlannerEventRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)

    task = starter.execute_existing_main_chat_task(
        task_id="task-quit",
        conversation_id="chat-1",
        prompt="退出 Slack",
    )

    assert task is not None
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["daily_desktop_tool"] == "app.quit"
    assert metadata["daily_desktop_source"] == "runtime_planner"
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    assert model_loop_call[1]["direct_tool_requests"] == []
    selection_events = [
        event for event in runtime.calls if event[0] == "append_run_event"
        and event[1]["event_type"] == "agent.plan.selection"
    ]
    assert selection_events[0][1]["payload"]["plan_tools"] == [
        "desktop.list_apps",
        "app.quit",
        "desktop.running_apps",
    ]
    assert selection_events[0][1]["payload"]["selected_tools"] == ["app.quit"]


def test_legacy_chat_task_starter_does_not_pass_hotkey_safe_shortcut_full_plan() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatPlannerEventRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)

    task = starter.execute_existing_main_chat_task(
        task_id="task-hotkey",
        conversation_id="chat-1",
        prompt="你能帮我按Command L吗",
    )

    assert task is not None
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["daily_desktop_tool"] == "desktop.safe_shortcut"
    assert metadata["daily_desktop_source"] == "runtime_planner"
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    assert model_loop_call[1]["direct_tool_requests"] == []
    selection_events = [
        event for event in runtime.calls if event[0] == "append_run_event"
        and event[1]["event_type"] == "agent.plan.selection"
    ]
    assert selection_events[0][1]["payload"]["selection_source"] == "runtime_planner"
    assert selection_events[0][1]["payload"]["selected_tools"] == ["desktop.safe_shortcut"]


def test_legacy_chat_task_starter_uses_main_chat_tools_for_runtime_planner() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatDataAnalysisRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)

    task = starter.execute_existing_main_chat_task(
        task_id="task-data",
        conversation_id="chat-1",
        prompt="请分析 data/sales.csv 并输出报告",
    )

    assert task is not None
    assert task["task_id"] == "task-data"
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "data_analysis"
    assert metadata["daily_desktop_tool"] == "data.analyze"
    assert metadata["daily_desktop_source"] == "runtime_planner"
    assert metadata["daily_desktop_planning_reason"] == "planner_builtin_data_analysis"
    planner_events = [call for call in runtime.calls if call[0] == "append_run_event"]
    assert planner_events[0][1]["payload"]["intent"]["kind"] == "data_analysis"
    assert planner_events[1][1]["payload"]["plan"]["tool_plan"]["steps"][0]["tool_name"] == (
        "data.analyze"
    )
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    assert [request["tool"] for request in model_loop_call[1]["direct_tool_requests"]] == [
        "data.analyze"
    ]


def test_legacy_runtime_port_readiness_includes_desktop_execution_capabilities(monkeypatch) -> None:
    runtime = _FakeRuntime()
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_permission_missing_by_capability",
        lambda: {},
    )

    readiness = LegacyRuntimePort(runtime).readiness()
    capabilities = readiness["capabilities"]

    assert readiness["ok"] is True
    assert capabilities["tasks"] is True
    assert capabilities["runnables"] == 1
    assert capabilities["desktop_execution"]["platform"] in {
        "macos",
        "windows",
        "linux",
        "unknown",
    }
    assert capabilities["desktop_execution"]["available"] is (
        capabilities["desktop_execution"]["platform"] == "macos"
    )
    assert "screen.capture" in capabilities["screen_capture"]["tools"]
    assert "desktop.click" in capabilities["foreground_input"]["tools"]
    assert capabilities["foreground_input"]["risk_default"] == "medium"
    assert runtime.calls == [("list_runnables", None)]


def test_legacy_runtime_port_readiness_reports_desktop_permission_gaps(monkeypatch) -> None:
    runtime = _FakeRuntime()
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_permission_missing_by_capability",
        lambda: {
            "screen_capture": ["screen_recording"],
            "foreground_input": ["accessibility"],
        },
    )

    readiness = LegacyRuntimePort(runtime).readiness()
    capabilities = readiness["capabilities"]

    assert capabilities["screen_capture"]["missing_permissions"] == ["screen_recording"]
    assert capabilities["screen_capture"]["available"] is False
    assert capabilities["foreground_input"]["missing_permissions"] == ["accessibility"]
    assert capabilities["foreground_input"]["available"] is False
    assert runtime.calls == [("list_runnables", None)]


def test_legacy_runtime_port_starts_and_links_chat_workflow_task() -> None:
    runtime = _FakeRuntime()

    task = LegacyRuntimePort(runtime).start_chat_task(
        {
            "prompt": "Build report",
            "conversation_id": "chat-1",
            "client_task_id": "task-workflow-1",
            "workflow_id": "workflow-1",
        }
    )

    assert task["task_id"] == "task-workflow-1"
    assert task["conversation_id"] == "chat-1"
    assert task["open_in_studio_url"] == "#/agents?run_id=workflow-run-1"
    assert (
        "create_workflow_run",
        {
            "workflow_id": "workflow-1",
            "user_goal": "Build report",
            "source": "yachiyo_chat",
            "client_run_id": "task-workflow-1",
        },
    ) in runtime.calls
    assert (
        "link_task_run",
        {"task_id": "task-workflow-1", "run_id": "workflow-run-1", "session_id": "chat-1"},
    ) in runtime.calls


def test_legacy_runtime_port_preserves_workflow_identity_after_task_approval() -> None:
    runtime = _FakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Build report",
            "conversation_id": "chat-1",
            "client_task_id": "task-workflow-1",
            "workflow_id": "workflow-1",
        }
    )

    approved = port.approve("task-workflow-1")
    rejected = port.reject(
        "task-workflow-1",
        {
            "approved": False,
            "reason": "No",
            "metadata": {"approval_id": "approval-workflow-1"},
        },
    )

    assert approved["task_id"] == "task-workflow-1"
    assert approved["status"] == "completed"
    assert approved["kind"] == "workflow_run"
    assert approved["workflow_run_id"] == "workflow-run-1"
    assert approved["workflow_id"] == "workflow-1"
    assert rejected["task_id"] == "task-workflow-1"
    assert rejected["status"] == "failed"
    assert rejected["kind"] == "workflow_run"
    assert rejected["workflow_run_id"] == "workflow-run-1"
    assert rejected["workflow_id"] == "workflow-1"
    assert ("approve_run_approval", "workflow-run-1") in runtime.calls
    assert ("reject_run_approval", {"run_id": "workflow-run-1", "reason": "No"}) in runtime.calls


def test_legacy_runtime_port_resolves_task_link_for_approval_actions() -> None:
    runtime = _FakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    approved = port.approve("task-1")

    assert approved["task_id"] == "task-1"
    assert approved["session_id"] == "chat-1"
    assert approved["task_run_link_run_status"] == "running"
    assert ("approve_run_approval", "run-1") in runtime.calls
    assert ("get_task_run_link", "task-1") in runtime.calls


def test_legacy_runtime_port_honors_matching_task_approval_id() -> None:
    runtime = _FakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    approved = port.approve("task-1", {"approval_id": "approval-1"})

    assert approved["status"] == "completed"
    assert ("approve_run_approval", "run-1") in runtime.calls


def test_legacy_runtime_port_rejects_mismatched_task_approval_id() -> None:
    runtime = _FakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    with pytest.raises(AgentRuntimeError, match="审批 ID 与当前待审批项不匹配"):
        port.approve("task-1", {"approval_id": "wrong-approval"})

    assert ("approve_run_approval", "run-1") not in runtime.calls


def test_legacy_runtime_port_resolves_task_link_for_timeline() -> None:
    runtime = _FakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    timeline = port.get_task_timeline("task-1")

    assert timeline["run_id"] == "run-1"
    assert timeline["task_id"] == "task-1"
    assert timeline["session_id"] == "chat-1"
    assert timeline["task_run_link_run_status"] == "running"
    assert timeline["task_run_link_last_event_sequence"] == 1
    assert timeline["timeline"][0]["event"] == "run.started"
    assert ("get_task_run_link", "task-1") in runtime.calls


def test_legacy_runtime_port_resolves_task_link_for_event_stream() -> None:
    runtime = _FakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    events = port.get_task_event_stream("task-1")

    assert events["run_id"] == "run-1"
    assert events["events"][0]["event"] == "run.started"
    assert ("list_run_events", "run-1") in runtime.calls


def test_legacy_runtime_port_resolves_task_link_for_event_page_fallback() -> None:
    runtime = _FakeRuntime()
    runtime.runs["run-1"]["timeline"] = [
        {"event": "run.started"},
        {"event": "agent.progress"},
    ]
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    page = port.get_task_event_page("task-1", after_sequence=1, limit=1)

    assert page["run_id"] == "run-1"
    assert page["after_sequence"] == 1
    assert page["limit"] == 1
    assert page["next_after_sequence"] == 2
    assert page["has_more"] is False
    assert page["events"] == [{"event": "agent.progress"}]
    assert ("list_run_events", "run-1") in runtime.calls


def test_legacy_runtime_port_prefers_runtime_event_page_for_task_events() -> None:
    runtime = _PagedFakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    page = port.get_task_event_page("task-1", after_sequence=-2, limit=999)

    assert page["run_id"] == "run-1"
    assert page["after_sequence"] == 0
    assert page["limit"] == 500
    assert page["next_after_sequence"] == 5
    assert page["has_more"] is True
    assert page["events"] == [{"event": "agent.progress", "sequence": 5}]
    assert (
        "get_run_event_page",
        {"run_id": "run-1", "after_sequence": 0, "limit": 500},
    ) in runtime.calls
    assert ("list_run_events", "run-1") not in runtime.calls


def test_legacy_runtime_port_resolves_task_link_for_artifact_read() -> None:
    runtime = _FakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    artifact = port.read_task_artifact("task-1", "reports/out.md")

    assert artifact["run_id"] == "run-1"
    assert artifact["task_id"] == "task-1"
    assert artifact["path"] == "reports/out.md"
    assert artifact["content"] == "# Report"
    assert ("read_run_artifact", {"run_id": "run-1", "artifact_path": "reports/out.md"}) in runtime.calls


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.runs = {
            "run-1": {
                "run_id": "run-1",
                "user_goal": "Patch README",
                "status": "running",
                "pending_approval": {"approval_id": "approval-1"},
                "timeline": [{"event": "run.started"}],
            },
            "workflow-run-1": {
                "run_id": "workflow-run-1",
                "kind": "workflow_run",
                "workflow_run_id": "workflow-run-1",
                "workflow_id": "workflow-1",
                "user_goal": "Build report",
                "status": "running",
                "pending_approval": {"approval_id": "approval-workflow-1"},
                "timeline": [{"event": "workflow.run.started"}],
            },
        }
        self.task_links: dict[str, dict[str, Any]] = {}

    def list_runnables(self) -> dict[str, Any]:
        self.calls.append(("list_runnables", None))
        return {"runnables": [{"id": "builtin:yachiyo-main"}]}

    def create_run_for_runnable_async(self, **payload: Any) -> dict[str, Any]:
        self.calls.append(("create_run_for_runnable_async", payload))
        return dict(self.runs["run-1"])

    def create_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_workflow_run", payload))
        return dict(self.runs["workflow-run-1"])

    def get_run(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run", run_id))
        return dict(self.runs[run_id])

    def list_run_events(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("list_run_events", run_id))
        return {"events": list(self.runs[run_id]["timeline"])}

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        self.calls.append(
            ("read_run_artifact", {"run_id": run_id, "artifact_path": artifact_path})
        )
        return {
            "ok": True,
            "run_id": run_id,
            "path": artifact_path,
            "content": "# Report",
        }

    def link_task_run(self, *, task_id: str, run_id: str, session_id: str = "") -> dict[str, Any]:
        self.calls.append(
            ("link_task_run", {"task_id": task_id, "run_id": run_id, "session_id": session_id})
        )
        self.task_links[task_id] = {
            "task_id": task_id,
            "run_id": run_id,
            "session_id": session_id,
            "run_status": self.runs[run_id]["status"],
            "last_event_sequence": 1,
            "created_at": "2026-06-14T00:00:00Z",
            "updated_at": "2026-06-14T00:00:02Z",
        }
        return self.task_links[task_id]

    def get_task_run_link(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_run_link", task_id))
        try:
            return self.task_links[task_id]
        except KeyError:
            raise KeyError(task_id) from None

    def approve_run_approval(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("approve_run_approval", run_id))
        return {
            "run_id": run_id,
            "user_goal": "Patch README",
            "status": "completed",
        }

    def reject_run_approval(self, run_id: str, reason: str = "") -> dict[str, Any]:
        self.calls.append(("reject_run_approval", {"run_id": run_id, "reason": reason}))
        return {
            "run_id": run_id,
            "user_goal": "Patch README",
            "status": "failed",
        }


class _PagedFakeRuntime(_FakeRuntime):
    def get_run_event_page(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "get_run_event_page",
                {
                    "run_id": run_id,
                    "after_sequence": after_sequence,
                    "limit": limit,
                },
            )
        )
        return {
            "run_id": run_id,
            "after_sequence": after_sequence,
            "limit": limit,
            "next_after_sequence": 5,
            "has_more": True,
            "events": [{"event": "agent.progress", "sequence": 5}],
        }


class _PlannerEventFakeRuntime(_FakeRuntime):
    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.calls.append(
            (
                "append_run_event",
                {
                    "run_id": run_id,
                    "event_type": event_type,
                    "payload": payload,
                },
            )
        )


class _FakeChatSession:
    session_id = "chat-1"

    def __init__(self) -> None:
        self.metadata_calls: list[dict[str, Any]] = []
        self.assistant_messages: list[dict[str, Any]] = []

    def update_message_metadata_for_task(
        self,
        task_id: str,
        metadata: dict[str, Any],
        *,
        role: str,
    ) -> None:
        self.metadata_calls.append(
            {
                "task_id": task_id,
                "metadata": metadata,
                "role": role,
            }
        )

    def upsert_assistant_message(self, **payload: Any) -> None:
        self.assistant_messages.append(payload)


class _FakeAppState:
    def __init__(self) -> None:
        self.status_calls: list[dict[str, Any]] = []

    def update_task_status(self, task_id: str, status: Any, **payload: Any) -> None:
        self.status_calls.append({"task_id": task_id, "status": status, **payload})


class _FakeAppRuntime:
    def __init__(self) -> None:
        self.chat_session = _FakeChatSession()
        self.state = _FakeAppState()


class _MainChatPlannerEventRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def start_main_chat_run(
        self,
        *,
        task_id: str,
        session_id: str,
        user_goal: str,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "start_main_chat_run",
                {
                    "task_id": task_id,
                    "session_id": session_id,
                    "user_goal": user_goal,
                },
            )
        )
        return {
            "run_id": "run-main",
            "task_id": task_id,
            "session_id": session_id,
            "user_goal": user_goal,
            "status": "running",
        }

    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.calls.append(
            (
                "append_run_event",
                {
                    "run_id": run_id,
                    "event_type": event_type,
                    "payload": payload,
                },
            )
        )

    def execute_main_chat_model_loop(
        self,
        run_id: str,
        messages: list[dict[str, Any]],
        *,
        direct_tool_request: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "execute_main_chat_model_loop",
                {
                    "run_id": run_id,
                    "messages": messages,
                    "direct_tool_request": direct_tool_request,
                    "direct_tool_requests": direct_tool_requests,
                },
            )
        )
        return {"run_id": run_id, "status": "completed", "result": "Done"}

    def complete_main_chat_run(self, run_id: str, result: str) -> dict[str, Any]:
        self.calls.append(("complete_main_chat_run", {"run_id": run_id, "result": result}))
        return {"run_id": run_id, "status": "completed", "result": result}


class _MainChatDataAnalysisRuntime(_MainChatPlannerEventRuntime):
    def _main_chat_tool_policy(self) -> dict[str, Any]:
        return {
            "allowed_tools": ["data.analyze", "workspace.read", "terminal.run", "artifact.write"],
            "approval_required": {},
        }
