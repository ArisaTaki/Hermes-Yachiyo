"""Legacy Chat task runtime port adapter tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.yachiyo_agent.daily_desktop import (
    daily_desktop_allowed_tools,
    desktop_agent_entrypoint_allowed_tools,
    direct_browser_entrypoint_requests,
    main_chat_entrypoint_allowed_tools,
    planner_first_daily_desktop_entrypoint_requests,
)
from apps.shell.yachiyo_agent import legacy_ports as legacy_ports_module
from apps.shell.yachiyo_agent.legacy_ports import (
    LegacyChatTaskStarter,
    LegacyRuntimePort as CompatLegacyRuntimePort,
    LegacyStudioPort,
)
from apps.shell.yachiyo_agent.legacy_tasks import LegacyRuntimePort
from apps.shell.yachiyo_agent.legacy_cleanup_coverage import (
    legacy_daily_desktop_cleanup_coverage,
    migrated_daily_desktop_prompts,
)
from apps.shell.yachiyo_agent.entrypoint_tool_selection import (
    DirectToolSelection,
    planner_first_direct_tool_selection,
)
from apps.shell.yachiyo_agent.planner_projection import planner_enriched_chat_request
from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner


def test_desktop_agent_entrypoint_fallback_includes_analysis_tools() -> None:
    allowed_tools = desktop_agent_entrypoint_allowed_tools()

    assert "desktop.list_apps" in allowed_tools
    assert "app.open" in allowed_tools
    assert "workspace.read" in allowed_tools
    assert "data.analyze" in allowed_tools
    assert "terminal.run" in allowed_tools
    assert "python.run" in allowed_tools
    assert "artifact.write" in allowed_tools
    assert len(allowed_tools) == len(set(allowed_tools))


def test_main_chat_entrypoint_extends_explicit_runtime_tool_policy() -> None:
    class Runtime:
        @staticmethod
        def _main_chat_tool_policy() -> dict[str, Any]:
            return {"allowed_tools": ["workspace.read"]}

    allowed_tools = main_chat_entrypoint_allowed_tools(Runtime())

    assert allowed_tools[0] == "workspace.read"
    assert "desktop.list_apps" in allowed_tools
    assert "app.open" in allowed_tools
    assert "media.music_app_open_and_play" in allowed_tools
    assert "python.run" in allowed_tools
    assert len(allowed_tools) == len(set(allowed_tools))


def test_main_chat_direct_request_tool_policy_includes_selected_tools() -> None:
    policy = legacy_ports_module._main_chat_direct_request_tool_policy(
        None,
        [
            {"tool": "desktop.list_apps", "input": {"query": "Music"}},
            {"tool": "media.music_app_open_and_play", "input": {"app_name": "Music"}},
        ],
    )

    assert policy["allowed_tools"] == [
        "desktop.list_apps",
        "media.music_app_open_and_play",
    ]


def test_desktop_agent_entrypoint_fallback_routes_data_analysis() -> None:
    requests = planner_first_daily_desktop_entrypoint_requests(
        "请分析 data/sales.csv 并输出报告",
        allowed_tools=desktop_agent_entrypoint_allowed_tools(),
    )

    assert [request["tool"] for request in requests] == ["data.analyze"]
    assert requests[0]["input"] == {
        "path": "data/sales.csv",
        "artifact_path": "analysis-report.md",
        "source_kind": "csv",
        "requested_outputs": ["report"],
        "artifact_manifest": [{"path": "analysis-report.md", "kind": "markdown"}],
    }


def test_daily_entrypoint_keeps_discover_operate_verify_direct_execution() -> None:
    requests = planner_first_daily_desktop_entrypoint_requests(
        "Can you play Apple Music?",
        allowed_tools=desktop_agent_entrypoint_allowed_tools(),
        execution_normalized=True,
        include_runtime_context=True,
    )

    assert [request["tool"] for request in requests] == [
        "media.music_app_open_and_play",
        "desktop.ui_elements",
    ]
    assert requests[0]["runtime_stage"] == "operate"
    assert requests[-1]["runtime_stage"] == "verify"


def test_daily_entrypoint_executes_read_only_active_window_verify() -> None:
    requests = planner_first_daily_desktop_entrypoint_requests(
        "打开微信",
        allowed_tools=desktop_agent_entrypoint_allowed_tools(),
        execution_normalized=True,
        include_runtime_context=True,
    )

    assert [request["tool"] for request in requests] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert requests[-1]["runtime_stage"] == "verify"
    assert [
        bool(request.get("continue_to_model"))
        for request in requests
    ] == [False, False, True]


def test_desktop_agent_entrypoint_prefetches_report_research_context() -> None:
    requests = planner_first_daily_desktop_entrypoint_requests(
        "创建一份竞品分析报告，保存成 markdown",
        allowed_tools=desktop_agent_entrypoint_allowed_tools(),
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url_and_extract_text",
            "input": {
                "url": "https://www.google.com/search?q=%E7%AB%9E%E5%93%81%E5%88%86%E6%9E%90"
            },
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_report_context",
            "continue_to_model": True,
        }
    ]


def test_direct_browser_entrypoint_ignores_artifact_followup_for_simple_open() -> None:
    requests = [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://github.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
            "continue_to_model": True,
        }
    ]

    assert direct_browser_entrypoint_requests(requests, "打开 GitHub") == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://github.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert direct_browser_entrypoint_requests(requests, "调研 GitHub 并输出报告") == []


def _recording_legacy_requests(
    calls: list[dict[str, Any]],
) -> Callable[[str, list[str]], list[dict[str, Any]]]:
    def record(prompt: str, allowed_tools: list[str]) -> list[dict[str, Any]]:
        calls.append({"prompt": prompt, "allowed_tools": list(allowed_tools)})
        return []

    return record


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
    create_call = runtime.calls[0]
    assert create_call[0] == "create_run_for_runnable_async"
    assert create_call[1]["runnable_id"] == "builtin:yachiyo-main"
    assert create_call[1]["user_goal"] == "Patch README"
    assert create_call[1]["runtime_planner_entrypoint"] is True
    assert create_call[1]["daily_desktop_planning_context"] == "Patch README"
    assert [request["tool"] for request in create_call[1]["direct_tool_requests"]] == [
        "workspace.list",
        "workspace.read",
    ]
    assert runtime.calls[1:] == [
        ("link_task_run", {"task_id": "task-1", "run_id": "run-1", "session_id": "chat-1"}),
        ("get_run", "run-1"),
        ("list_run_events", "run-1"),
    ]


def test_legacy_runtime_port_forwards_runtime_execution_plan_to_runnable_run() -> None:
    runtime = _FakeRuntime()
    request = planner_enriched_chat_request(
        {
            "prompt": "请分析 data/sales.csv 并输出报告",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    task = LegacyRuntimePort(runtime).start_chat_task(request)

    create_call = next(
        payload
        for call_name, payload in runtime.calls
        if call_name == "create_run_for_runnable_async"
    )
    direct_requests = create_call["direct_tool_requests"]
    assert task["task_id"] == "task-1"
    assert create_call["runtime_planner_entrypoint"] is True
    assert create_call["daily_desktop_planning_context"] == "请分析 data/sales.csv 并输出报告"
    assert create_call["metadata"]["yachiyo_runtime_planner"] is True
    assert create_call["runtime_execution_envelope"]["intent_kind"] == "data_analysis"
    assert [request["tool"] for request in direct_requests] == [
        "workspace.read",
        "data.analyze",
    ]
    assert direct_requests[0]["step_id"] == "read-data-source"
    assert direct_requests[1]["step_id"] == "analyze-data-file"
    assert direct_requests[1]["checkpoint_policy"][
        "requires_post_action_verification"
    ] is True
    assert "daily_desktop_policy_overlay" not in create_call


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
    planner_event_types = [event[1]["event_type"] for event in planner_events]
    assert task["task_id"] == "task-1"
    assert planner_event_types[:4] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.plan.step",
    ]
    assert "agent.task.todo.updated" in planner_event_types
    assert "agent.task.checkpoint.updated" in planner_event_types
    assert planner_events[0][1]["payload"]["intent"]["kind"] == "data_analysis"
    assert planner_events[1][1]["payload"]["plan"]["tool_plan"]["artifacts_expected"] == [
        "analysis-report.md",
    ]
    task_core_event = next(
        event for event in planner_events
        if event[1]["event_type"] == "agent.task_core.created"
    )
    assert task_core_event[1]["payload"]["todo_count"] >= 1
    assert task_core_event[1]["payload"]["checkpoint_count"] >= 1
    assert planner_events[3][1]["payload"]["step"]["tool_name"] == "data.analyze"


def test_legacy_runtime_port_appends_desktop_readiness_blocked_plan_events(monkeypatch) -> None:
    runtime = _PlannerEventFakeRuntime()
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_permission_missing_by_capability",
        lambda: {},
    )
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_runtime_blocking_conditions_by_capability",
        lambda: {
            "foreground_activation": ["foreground_focus_unavailable"],
        },
    )

    task = LegacyRuntimePort(runtime).start_chat_task(
        {
            "prompt": "打开 PixelForge 并点击导出按钮",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    planner_events = [call for call in runtime.calls if call[0] == "append_run_event"]
    plan = planner_events[1][1]["payload"]["plan"]["tool_plan"]
    steps = {step["step_id"]: step for step in plan["steps"]}

    assert task["task_id"] == "task-1"
    assert plan["missing_capabilities"] == ["desktop.ui_operation"]
    if "discover-desktop-state" in steps:
        assert steps["discover-desktop-state"]["status"] == "planned"
    assert steps["operate-foreground-ui"]["status"] == "unavailable"
    assert steps["operate-foreground-ui"]["input_preview"]["blocking_conditions"] == [
        "foreground_focus_unavailable"
    ]


def test_legacy_runtime_port_appends_read_only_file_inventory_plan_events() -> None:
    runtime = _PlannerEventFakeRuntime()

    task = LegacyRuntimePort(runtime).start_chat_task(
        {
            "prompt": "整理出 Downloads 里的文件清单",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    planner_events = [call for call in runtime.calls if call[0] == "append_run_event"]
    plan = planner_events[1][1]["payload"]["plan"]["tool_plan"]
    assert task["task_id"] == "task-1"
    assert planner_events[0][1]["payload"]["intent"]["kind"] == "file_organization"
    assert planner_events[0][1]["payload"]["intent"]["inputs"]["operation_hint"] == "inventory"
    assert plan["artifacts_expected"] == ["file-inventory.md"]
    assert plan["approvals_required"] == []
    assert [step["step_id"] for step in plan["steps"]] == [
        "inspect-file-scope",
        "write-file-organization-plan",
    ]


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
        "agent.task_core.created",
        "agent.plan.step",
        "agent.plan.step",
    ]
    assert planner_events[0][1]["payload"]["intent"]["kind"] == "media_playback"
    plan = planner_events[1][1]["payload"]["plan"]
    capabilities = {
        capability["capability_id"]: capability
        for capability in plan["capabilities"]
    }
    assert "media.playback" in capabilities
    assert [step["tool_name"] for step in plan["tool_plan"]["steps"]] == [
        "media.music_app_open_and_play",
        "desktop.ui_elements",
    ]


def test_planner_first_direct_selection_owns_media_playback_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    selection = planner_first_direct_tool_selection(
        "播放超时空辉夜姬",
        ["media.apple_music_play"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
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
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_music_app_search_play_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    selection = planner_first_direct_tool_selection(
        "打开 Spotify 搜索 Taylor Swift 并播放",
        [
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "media.music_app_open_and_play",
        ],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert selection.selected_source == "runtime_planner"
    assert [request["tool"] for request in selection.requests] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "media.music_app_open_and_play",
    ]
    assert selection.requests[-1]["input"] == {"app_name": "Spotify"}
    assert selection.event_payload["legacy_request_count"] == 0
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_clipboard_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    write_selection = planner_first_direct_tool_selection(
        "copy hello world to clipboard",
        ["clipboard.write"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    set_selection = planner_first_direct_tool_selection(
        "设置剪贴板为 hello world",
        ["clipboard.write"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    short_copy_selection = planner_first_direct_tool_selection(
        "把 hello world 复制一下",
        ["clipboard.write"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    read_selection = planner_first_direct_tool_selection(
        "read selected text",
        ["desktop.safe_shortcut", "clipboard.read"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
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
    assert set_selection.selected_source == "runtime_planner"
    assert set_selection.requests == write_selection.requests
    assert set_selection.event_payload["legacy_request_count"] == 0
    assert short_copy_selection.selected_source == "runtime_planner"
    assert short_copy_selection.requests == write_selection.requests
    assert short_copy_selection.event_payload["legacy_request_count"] == 0
    assert read_selection.selected_source == "runtime_planner"
    assert read_selection.event_payload["legacy_request_count"] == 0
    assert [request["tool"] for request in read_selection.requests] == [
        "desktop.safe_shortcut",
        "clipboard.read",
    ]
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_system_control_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    volume_selection = planner_first_direct_tool_selection(
        "大点声",
        ["system.volume"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    screen_saver_selection = planner_first_direct_tool_selection(
        "启动屏幕保护程序",
        ["system.settings_open", "system.screen_saver_start"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
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
        {
            "protocol": "json_fallback",
            "tool": "system.volume",
            "input": {"action": "status"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_system_control",
            "continue_to_model": True,
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
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_web_research_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    selection = planner_first_direct_tool_selection(
        "open https://example.com",
        ["browser.open_url"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
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
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_current_page_web_actions_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    allowed = ["browser.current_page", "browser.extract_text", "browser.screenshot"]

    link_selection = planner_first_direct_tool_selection(
        "读取当前网页链接",
        allowed,
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    summary_selection = planner_first_direct_tool_selection(
        "概括当前网页内容",
        allowed,
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    screenshot_selection = planner_first_direct_tool_selection(
        "当前网页截图",
        allowed,
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert link_selection.selected_source == "runtime_planner"
    assert link_selection.event_payload["legacy_request_count"] == 0
    assert link_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.current_page",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert summary_selection.selected_source == "runtime_planner"
    assert summary_selection.event_payload["legacy_request_count"] == 0
    assert summary_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.extract_text",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
            "presentation": "summary",
            "continue_to_model": True,
        }
    ]
    assert screenshot_selection.selected_source == "runtime_planner"
    assert screenshot_selection.event_payload["legacy_request_count"] == 0
    assert screenshot_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.screenshot",
            "input": {"reason": "user asked to capture the browser page"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_app_scoped_dynamic_browser_context_without_legacy() -> None:
    allowed = [
        "desktop.safe_shortcut",
        "desktop.search_submit",
        "app.open_and_safe_shortcut",
    ]
    cases = (
        (
            "用 Safari 搜索选中的内容",
            [
                "desktop.safe_shortcut",
                "app.open_and_safe_shortcut",
                "desktop.safe_shortcut",
                "desktop.search_submit",
            ],
        ),
        (
            "open selected link in Safari",
            [
                "desktop.safe_shortcut",
                "app.open_and_safe_shortcut",
                "desktop.safe_shortcut",
                "desktop.search_submit",
            ],
        ),
    )
    for prompt, expected_tools in cases:
        legacy_calls: list[dict[str, Any]] = []
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.event_payload["selected_tools"] == expected_tools
        assert legacy_calls == []


def test_planner_first_direct_selection_owns_current_page_link_copy_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    for prompt in (
        "把当前网页链接复制给我",
        "把当前链接复制给我",
        "当前页地址复制一下",
        "copy current page link to clipboard",
    ):
        selection = planner_first_direct_tool_selection(
            prompt,
            ["desktop.safe_shortcut"],
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.requests == [
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_shortcut",
                "input": {"action": "copy_current_page_link"},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            }
        ]

    assert legacy_calls == []


def test_planner_first_direct_selection_owns_screenshot_shortcuts_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    cases = (
        ("截取选区", "screenshot_selection"),
        ("capture selected area", "screenshot_selection"),
        ("打开截图工具", "screenshot_toolbar"),
        ("打开截图面板", "screenshot_toolbar"),
        ("open screenshot toolbar", "screenshot_toolbar"),
        ("打开录屏工具", "screenshot_toolbar"),
        ("screen recording toolbar", "screenshot_toolbar"),
    )

    for prompt, action in cases:
        selection = planner_first_direct_tool_selection(
            prompt,
            ["desktop.running_apps", "app.open", "desktop.safe_shortcut", "desktop.ui_elements"],
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.requests == [
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_shortcut",
                "input": {"action": action},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.ui_elements",
                "input": {},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            },
        ]

    assert legacy_calls == []


def test_planner_first_direct_selection_owns_dynamic_context_ui_transfer_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    allowed = [
        "desktop.safe_shortcut",
        "desktop.click_ui_element",
        "app.focus_and_safe_shortcut",
        "app.open_and_safe_shortcut",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
    ]

    cases = (
        (
            "把当前网页链接粘贴到 Slack",
            ["desktop.safe_shortcut", "app.focus_and_safe_shortcut"],
        ),
        (
            "在 Slack 粘贴当前页面内容",
            ["desktop.safe_shortcut", "desktop.safe_shortcut", "app.focus_and_safe_shortcut"],
        ),
        (
            "打开 Slack 粘贴当前页面内容",
            ["desktop.safe_shortcut", "desktop.safe_shortcut", "app.open_and_safe_shortcut"],
        ),
        (
            "把剪贴板内容粘贴到 Slack",
            ["app.focus_and_safe_shortcut"],
        ),
        (
            "把当前网页链接输入到 Slack 搜索框",
            ["desktop.safe_shortcut", "app.focus_and_click_ui_element", "desktop.safe_shortcut"],
        ),
        (
            "打开 Slack 搜索框输入选中的内容",
            ["desktop.safe_shortcut", "app.open_and_click_ui_element", "desktop.safe_shortcut"],
        ),
        (
            "复制当前网页内容",
            ["desktop.safe_shortcut", "desktop.safe_shortcut"],
        ),
        (
            "把选中的内容填到当前输入框",
            ["desktop.safe_shortcut", "desktop.safe_shortcut"],
        ),
        (
            "把剪贴板内容填到当前输入框",
            ["desktop.safe_shortcut"],
        ),
    )
    for prompt, expected_tools in cases:
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.event_payload["selected_tools"] == expected_tools

    assert legacy_calls == []


def test_planner_first_direct_selection_owns_app_search_dynamic_context_without_legacy() -> None:
    allowed = [
        "desktop.list_apps",
        "app.focus",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.ui_elements",
    ]
    cases = (
        (
            "在微信里查找选中的内容",
            [
                "desktop.list_apps",
                "desktop.safe_shortcut",
                "app.focus",
                "desktop.safe_shortcut",
                "desktop.safe_shortcut",
                "desktop.search_submit",
                "desktop.ui_elements",
            ],
        ),
        (
            "在 Slack 里查找剪贴板内容",
            [
                "desktop.list_apps",
                "app.focus",
                "desktop.safe_shortcut",
                "desktop.safe_shortcut",
                "desktop.search_submit",
                "desktop.ui_elements",
            ],
        ),
    )

    for prompt, expected_tools in cases:
        legacy_calls: list[dict[str, Any]] = []
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.event_payload["selected_tools"] == expected_tools
        assert legacy_calls == []


def test_planner_first_direct_selection_owns_schedule_and_empty_note_app_items_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    allowed = [
        "desktop.safe_shortcut",
        "app.open",
        "app.open_and_safe_shortcut",
        "browser.current_page",
        "reminders.create",
        "calendar.create_event",
    ]
    cases = (
        (
            "把当前网页链接加入提醒事项",
            ["desktop.safe_shortcut", "app.open_and_safe_shortcut", "desktop.safe_shortcut"],
        ),
        (
            "把当前网页链接加入日历",
            ["desktop.safe_shortcut", "app.open_and_safe_shortcut", "desktop.safe_shortcut"],
        ),
        ("创建备忘录", ["desktop.safe_shortcut"]),
    )

    for prompt, expected_tools in cases:
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.event_payload["selected_tools"] == expected_tools

    assert legacy_calls == []


def test_planner_first_direct_selection_owns_remaining_app_scoped_samples_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    allowed = [
        "desktop.list_apps",
        "desktop.active_window",
        "desktop.ui_elements",
        "app.focus",
        "app.focus_and_safe_shortcut",
        "app.open_and_safe_shortcut",
        "app.focus_and_click_ui_element",
        "desktop.close_window",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.submit_foreground",
    ]
    cases = (
        (
            "微信关闭窗口",
            ["desktop.list_apps", "app.focus", "desktop.close_window", "desktop.active_window"],
        ),
        (
            "在 VS Code 里执行命令 Format Document",
            [
                "desktop.list_apps",
                "app.focus_and_safe_shortcut",
                "desktop.safe_type_text",
                "desktop.submit_foreground",
                "desktop.ui_elements",
            ],
        ),
        (
            "Finder look for Downloads",
            [
                "desktop.list_apps",
                "app.focus_and_safe_shortcut",
                "desktop.safe_type_text",
                "desktop.search_submit",
                "desktop.ui_elements",
            ],
        ),
        (
            "微信打开搜索",
            ["desktop.list_apps", "app.focus_and_safe_shortcut", "desktop.ui_elements"],
        ),
        (
            "Chrome 点登录",
            ["desktop.list_apps", "app.focus", "desktop.ui_elements"],
        ),
    )

    for prompt, expected_tools in cases:
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.event_payload["selected_tools"] == expected_tools

    assert legacy_calls == []


def test_runtime_planner_covers_migrated_desktop_samples_before_cleanup() -> None:
    legacy_calls: list[dict[str, Any]] = []
    prompts = migrated_daily_desktop_prompts()
    coverage = legacy_daily_desktop_cleanup_coverage()
    sample_contracts = {
        contract["prompt"]: contract
        for contract in coverage["sample_contracts"]
    }
    planner = RuntimePlanner()
    allowed_tools = daily_desktop_allowed_tools()

    assert coverage["legacy_boundary"] == "legacy_daily_desktop_intent"
    assert coverage["planner_owner"] == "runtime_planner"
    assert coverage["total_samples"] == len(prompts)
    assert coverage["cleanup_readiness"] == "planner_covered_compat_cleanup_pending"
    assert coverage["remaining_fallback_count"] == 2
    assert coverage["planner_covered_fallback_count"] == 2
    assert coverage["compatibility_cleanup_pending_count"] == 2
    assert {
        contract["fallback_id"] for contract in coverage["remaining_fallback_contracts"]
    } == {
        "browser_search_and_app_scoped_search",
        "semantic_ui_targeting",
    }
    assert "context_transfer" in coverage["areas"]
    assert len(sample_contracts) == len(prompts)
    assert "desktop_operation" in coverage["covered_intents"]
    assert "desktop.app_discovery" in coverage["covered_capabilities"]
    assert "desktop.list_apps" in coverage["covered_tools"]

    remaining_legacy_prompts: list[str] = []
    for prompt in prompts:
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed_tools,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )
        contract = sample_contracts[prompt]
        decision = planner.decision(prompt, allowed_tools=allowed_tools)
        selected_tools = set(selection.event_payload["selected_tools"])
        contract_tools = set(contract["planner_tools"])
        contract_capabilities = set(contract["planner_capabilities"])
        if selection.selected_source != "runtime_planner":
            remaining_legacy_prompts.append(prompt)
        assert contract["cleanup_status"] == "planner_covered"
        assert decision.selected_intent.kind in contract["planner_intents"]
        assert set(decision.plan.tool_plan.required_capabilities).issubset(contract_capabilities)
        assert selected_tools.issubset(contract_tools)

    assert remaining_legacy_prompts == []
    assert legacy_calls == []


def test_runtime_planner_covers_remaining_fallback_contracts_before_compat_cleanup() -> None:
    legacy_calls: list[dict[str, Any]] = []
    coverage = legacy_daily_desktop_cleanup_coverage()
    allowed_tools = daily_desktop_allowed_tools()
    fallback_contracts = coverage["remaining_fallback_contracts"]

    assert fallback_contracts
    for contract in fallback_contracts:
        assert contract["status"] == "planner_covered_compat_cleanup_pending"
        assert contract["planner_coverage_status"] == "planner_covered"
        assert contract["cleanup_blocker"] == "legacy_response_shape_compatibility"
        assert contract["planner_evidence_prompts"] == contract["example_prompts"]
        for prompt in contract["planner_evidence_prompts"]:
            selection = planner_first_direct_tool_selection(
                prompt,
                allowed_tools,
                legacy_tool_requests=_recording_legacy_requests(legacy_calls),
            )

            assert selection.selected_source == "runtime_planner"
            assert selection.event_payload["legacy_request_count"] == 0
            assert selection.event_payload["selected_tools"]

    assert legacy_calls == []


def test_planner_first_direct_selection_owns_app_new_item_shortcuts_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    cases = (
        ("打开备忘录新建备忘录", "app.open_and_safe_shortcut", "Notes", "new_note"),
        ("备忘录新建", "app.focus_and_safe_shortcut", "Notes", "new_note"),
        ("打开提醒事项新建提醒", "app.open_and_safe_shortcut", "Reminders", "new_reminder"),
        ("提醒事项新建", "app.focus_and_safe_shortcut", "Reminders", "new_reminder"),
        ("打开日历新建日程", "app.open_and_safe_shortcut", "Calendar", "new_event"),
        ("Calendar new meeting", "app.focus_and_safe_shortcut", "Calendar", "new_event"),
        ("打开邮件新建邮件", "app.open_and_safe_shortcut", "Mail", "new_message"),
        ("Mail compose email", "app.focus_and_safe_shortcut", "Mail", "new_message"),
        ("打开 Mail 写邮件", "app.open_and_safe_shortcut", "Mail", "new_message"),
        ("Outlook 新建邮件", "app.focus_and_safe_shortcut", "Microsoft Outlook", "new_message"),
        ("打开 Outlook 写邮件", "app.open_and_safe_shortcut", "Microsoft Outlook", "new_message"),
        ("打开 Slack 新建消息", "app.open_and_safe_shortcut", "Slack", "new_message"),
        ("Slack 新建消息", "app.focus_and_safe_shortcut", "Slack", "new_message"),
        ("Slack new message", "app.focus_and_safe_shortcut", "Slack", "new_message"),
        ("微信新建聊天", "app.focus_and_safe_shortcut", "WeChat", "new_message"),
        ("Messages compose message", "app.focus_and_safe_shortcut", "Messages", "new_message"),
    )

    for prompt, tool_name, app_name, action in cases:
        selection = planner_first_direct_tool_selection(
            prompt,
            ["app.open_and_safe_shortcut", "app.focus_and_safe_shortcut"],
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": {"app_name": app_name, "action": action},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            }
        ]

    assert legacy_calls == []


def test_planner_first_direct_selection_owns_finder_special_locations_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    cases = (
        ("打开隔空投送", "app.open_and_safe_shortcut", "finder_airdrop"),
        ("打开 AirDrop", "app.open_and_safe_shortcut", "finder_airdrop"),
        ("Finder 打开隔空投送", "app.focus_and_safe_shortcut", "finder_airdrop"),
        ("打开网络位置", "app.open_and_safe_shortcut", "finder_network"),
        ("打开 Finder 网络", "app.open_and_safe_shortcut", "finder_network"),
        ("Finder 打开网络", "app.focus_and_safe_shortcut", "finder_network"),
        ("打开最近使用", "app.open_and_safe_shortcut", "finder_recents"),
        ("Finder 打开最近使用", "app.focus_and_safe_shortcut", "finder_recents"),
    )

    for prompt, tool_name, action in cases:
        selection = planner_first_direct_tool_selection(
            prompt,
            ["app.open_and_safe_shortcut", "app.focus_and_safe_shortcut", "system.settings_open"],
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": {"app_name": "Finder", "action": action},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            }
        ]

    network_settings = planner_first_direct_tool_selection(
        "打开网络",
        ["app.open_and_safe_shortcut", "app.focus_and_safe_shortcut", "system.settings_open"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    assert network_settings.selected_source == "runtime_planner"
    assert network_settings.requests == [
        {
            "protocol": "json_fallback",
            "tool": "system.settings_open",
            "input": {"target": "网络"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_system_control",
        }
    ]

    assert legacy_calls == []


def test_planner_first_direct_selection_owns_context_prefetch_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    data_selection = planner_first_direct_tool_selection(
        "分析 sales.csv 并输出报告",
        ["workspace.read"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    report_selection = planner_first_direct_tool_selection(
        "写一份项目总结报告",
        ["workspace.list", "workspace.read", "artifact.write"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    code_selection = planner_first_direct_tool_selection(
        "检查这个仓库的代码并总结风险",
        ["workspace.list", "workspace.read", "terminal.run", "artifact.write"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert data_selection.selected_source == "runtime_planner"
    assert data_selection.event_payload["legacy_request_count"] == 0
    assert data_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "workspace.read",
            "input": {"path": "sales.csv"},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_data_source",
            "continue_to_model": True,
        },
    ]
    assert report_selection.selected_source == "runtime_planner"
    assert report_selection.event_payload["legacy_request_count"] == 0
    assert report_selection.requests[0]["planning_reason"] == "planner_prefetch_report_context"
    assert report_selection.requests[0]["continue_to_model"] is True
    assert code_selection.selected_source == "runtime_planner"
    assert code_selection.event_payload["legacy_request_count"] == 0
    assert code_selection.requests[0]["planning_reason"] == "planner_prefetch_code_context"
    assert code_selection.requests[0]["continue_to_model"] is True
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_file_access_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    open_selection = planner_first_direct_tool_selection(
        "打开下载目录里的最新文件",
        ["desktop.open_path", "desktop.reveal_path"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    reveal_selection = planner_first_direct_tool_selection(
        "显示当前选中文件",
        ["desktop.open_path", "desktop.reveal_path"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert open_selection.selected_source == "runtime_planner"
    assert open_selection.event_payload["legacy_request_count"] == 0
    assert open_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.open_path",
            "input": {"path": "latest_download"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_file_access",
        }
    ]
    assert reveal_selection.selected_source == "runtime_planner"
    assert reveal_selection.event_payload["legacy_request_count"] == 0
    assert reveal_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.reveal_path",
            "input": {"path": "finder_selection"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_file_access",
        }
    ]
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_desktop_discovery_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    allowed = [
        "desktop.permissions",
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.list_apps",
        "desktop.windows",
        "screen.capture",
    ]

    permission_selection = planner_first_direct_tool_selection(
        "需要什么权限",
        allowed,
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    active_window_selection = planner_first_direct_tool_selection(
        "当前窗口是什么",
        allowed,
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    observe_window_selection = planner_first_direct_tool_selection(
        "看看当前窗口",
        allowed,
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    frontmost_selection = planner_first_direct_tool_selection(
        "现在前台是什么",
        allowed,
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    running_apps_selection = planner_first_direct_tool_selection(
        "当前有哪些 App 在运行",
        allowed,
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    list_apps_selection = planner_first_direct_tool_selection(
        "show installed apps",
        allowed,
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    capture_selection = planner_first_direct_tool_selection(
        "截取当前屏幕",
        allowed,
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    windows_selection = planner_first_direct_tool_selection(
        "显示 Slack 窗口列表",
        allowed,
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert permission_selection.selected_source == "runtime_planner"
    assert permission_selection.event_payload["legacy_request_count"] == 0
    assert permission_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.permissions",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert active_window_selection.selected_source == "runtime_planner"
    assert active_window_selection.event_payload["legacy_request_count"] == 0
    assert active_window_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert observe_window_selection.selected_source == "runtime_planner"
    assert observe_window_selection.event_payload["legacy_request_count"] == 0
    assert observe_window_selection.requests == active_window_selection.requests
    assert frontmost_selection.selected_source == "runtime_planner"
    assert frontmost_selection.event_payload["legacy_request_count"] == 0
    assert frontmost_selection.requests == active_window_selection.requests
    assert running_apps_selection.selected_source == "runtime_planner"
    assert running_apps_selection.event_payload["legacy_request_count"] == 0
    assert running_apps_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.running_apps",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert list_apps_selection.selected_source == "runtime_planner"
    assert list_apps_selection.event_payload["legacy_request_count"] == 0
    assert list_apps_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert capture_selection.selected_source == "runtime_planner"
    assert capture_selection.event_payload["legacy_request_count"] == 0
    assert capture_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert windows_selection.selected_source == "runtime_planner"
    assert windows_selection.event_payload["legacy_request_count"] == 0
    assert windows_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "Slack", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.windows",
            "input": {"app_name": "Slack"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_app_launch_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    open_selection = planner_first_direct_tool_selection(
        "打开 PixelForge",
        ["desktop.list_apps", "app.open", "app.focus", "browser.open_url"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    chinese_app_selection = planner_first_direct_tool_selection(
        "打开微信",
        ["desktop.list_apps", "app.open", "app.focus", "browser.open_url"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    focus_selection = planner_first_direct_tool_selection(
        "切到 Slack",
        ["desktop.list_apps", "app.open", "app.focus", "browser.open_url"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert open_selection.selected_source == "runtime_planner"
    assert open_selection.event_payload["legacy_request_count"] == 0
    assert open_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "PixelForge", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {
                "app_name": "PixelForge",
                "selection_source": "desktop.list_apps",
                "query": "PixelForge",
            },
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert chinese_app_selection.selected_source == "runtime_planner"
    assert chinese_app_selection.event_payload["legacy_request_count"] == 0
    assert chinese_app_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "WeChat", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {
                "app_name": "WeChat",
                "selection_source": "desktop.list_apps",
                "query": "WeChat",
            },
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert focus_selection.selected_source == "runtime_planner"
    assert focus_selection.event_payload["legacy_request_count"] == 0
    assert focus_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "Slack", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {
                "app_name": "Slack",
                "selection_source": "desktop.list_apps",
                "query": "Slack",
            },
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert legacy_calls == []


def test_planner_first_direct_selection_discovers_generic_app_create_targets() -> None:
    legacy_calls: list[dict[str, Any]] = []
    allowed_tools = [
        "desktop.list_apps",
        "app.open",
        "app.focus",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "desktop.safe_shortcut",
        "desktop.ui_elements",
    ]
    cases = (
        ("打开 Notion Calendar", "Notion Calendar", "app.open"),
        ("Use Figma to create a wireframe", "Figma", "app.focus_and_safe_shortcut"),
        ("在 FigJam 里新建一个 board", "FigJam", "app.focus_and_safe_shortcut"),
    )

    for prompt, app_name, primary_tool in cases:
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed_tools,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.requests[0] == {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": app_name, "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
        assert selection.requests[1]["tool"] == primary_tool
        assert selection.requests[1]["input"]["app_name"] == app_name
        assert selection.requests[1]["input"]["selection_source"] == "desktop.list_apps"
        assert selection.requests[1]["input"]["query"] == app_name
        if primary_tool.endswith("_safe_shortcut"):
            assert selection.requests[1]["input"]["action"] == "new_document"

    foreground_selection = planner_first_direct_tool_selection(
        "当前窗口新建文档",
        allowed_tools,
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert foreground_selection.selected_source == "runtime_planner"
    assert foreground_selection.requests[0] == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "new_document"},
        "source": "runtime_planner",
        "planning_reason": "planner_desktop_operation",
    }
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_app_management_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    allowed_tools = [
        "desktop.list_apps",
        "app.show",
        "app.minimize",
        "app.quit",
        "app.status",
        "desktop.running_apps",
        "browser.open_url",
    ]
    cases = [
        ("你能帮我显示Finder吗", "app.show", {"app_name": "Finder"}),
        ("你能帮我还原微信吗", "app.show", {"app_name": "WeChat"}),
        ("打开微信到前台", "app.show", {"app_name": "WeChat"}),
        ("把Chrome叫出来", "app.show", {"app_name": "Google Chrome"}),
        ("Could you quit Slack please?", "app.quit", {"app_name": "Slack"}),
        ("Could you minimize Chrome please?", "app.minimize", {"app_name": "Google Chrome"}),
        ("Chrome 开着吗", "app.status", {"app_name": "Google Chrome"}),
        ("Google Chrome 在运行吗", "app.status", {"app_name": "Google Chrome"}),
        ("检查一下 Slack 是否运行", "app.status", {"app_name": "Slack"}),
        ("Finder 是否运行", "app.status", {"app_name": "Finder"}),
    ]

    for prompt, tool_name, tool_input in cases:
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed_tools,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.requests[0]["tool"] == "desktop.list_apps"
        assert selection.requests[0]["input"]["limit"] == 20
        expected_requests = [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": tool_input,
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            },
        ]
        if tool_name != "app.status":
            expected_requests.append(
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.running_apps",
                    "input": {},
                    "source": "runtime_planner",
                    "planning_reason": "planner_desktop_operation",
                }
            )
        assert selection.requests[1:] == expected_requests
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_show_all_hidden_apps_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    selection = planner_first_direct_tool_selection(
        "显示所有隐藏应用",
        ["desktop.running_apps", "desktop.show_all_apps", "desktop.active_window"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.event_payload["legacy_request_count"] == 0
    assert selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.show_all_apps",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
    ]
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_approved_low_level_foreground_click_and_type_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    click_selection = planner_first_direct_tool_selection(
        "点击坐标 120, 240",
        ["desktop.active_window", "desktop.click"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    type_selection = planner_first_direct_tool_selection(
        "输入 hello",
        ["desktop.active_window", "desktop.type_text"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert click_selection.selected_source == "runtime_planner"
    assert click_selection.event_payload["legacy_request_count"] == 0
    assert click_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.click",
            "input": {"x": 120, "y": 240},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
    ]
    assert type_selection.selected_source == "runtime_planner"
    assert type_selection.event_payload["legacy_request_count"] == 0
    assert type_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.type_text",
            "input": {"text": "hello"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
    ]
    assert legacy_calls == []


def test_legacy_entrypoint_keeps_app_ui_approval_sequence() -> None:
    requests = [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_type_into_ui_element",
            "input": {
                "app_name": "Google Chrome",
                "target": "搜索",
                "text": "yachiyo",
                "role_filter": "text",
                "limit": 80,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
        },
    ]

    safe_requests = legacy_ports_module._safe_selected_entrypoint_tool_requests(
        "打开 Chrome 并在搜索框输入 yachiyo 并搜索",
        requests,
        [
            "app.open_and_type_into_ui_element",
            "desktop.hotkey",
            "desktop.active_window",
        ],
    )

    assert [request["tool"] for request in safe_requests] == [
        "app.open_and_type_into_ui_element",
        "desktop.hotkey",
    ]


def test_planner_first_direct_selection_owns_search_submit_and_spotlight_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    allowed_tools = [
        "desktop.search_submit",
        "desktop.submit_foreground",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "browser.open_url",
    ]
    cases = [
        (
            "提交当前搜索",
            [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.search_submit",
                    "input": {},
                    "source": "runtime_planner",
                    "planning_reason": "planner_desktop_operation",
                }
            ],
        ),
        (
            "press enter to search",
            [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.search_submit",
                    "input": {},
                    "source": "runtime_planner",
                    "planning_reason": "planner_desktop_operation",
                }
            ],
        ),
        (
            "打开聚焦搜索",
            [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "spotlight_search"},
                    "source": "runtime_planner",
                    "planning_reason": "planner_desktop_operation",
                }
            ],
        ),
        (
            "Spotlight 搜索 yachiyo",
            [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "spotlight_search"},
                    "source": "runtime_planner",
                    "planning_reason": "planner_desktop_operation",
                },
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_type_text",
                    "input": {"text": "yachiyo"},
                    "source": "runtime_planner",
                    "planning_reason": "planner_desktop_operation",
                },
            ],
        ),
        (
            "打开聚焦搜索 yachiyo",
            [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "spotlight_search"},
                    "source": "runtime_planner",
                    "planning_reason": "planner_desktop_operation",
                },
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_type_text",
                    "input": {"text": "yachiyo"},
                    "source": "runtime_planner",
                    "planning_reason": "planner_desktop_operation",
                },
            ],
        ),
    ]

    for prompt, expected_requests in cases:
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed_tools,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.requests == expected_requests
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_copy_and_app_hotkeys_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    allowed_tools = [
        "desktop.safe_shortcut",
        "desktop.hotkey",
        "app.open_and_hotkey",
        "app.focus_and_hotkey",
    ]
    cases = [
        (
            "复制选中文本",
            [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "copy"},
                    "source": "runtime_planner",
                    "planning_reason": "planner_desktop_operation",
                }
            ],
        ),
        (
            "微信按回车",
            [
                {
                    "protocol": "json_fallback",
                    "tool": "app.focus_and_hotkey",
                    "input": {"app_name": "WeChat", "key": "return", "modifiers": []},
                    "source": "runtime_planner",
                    "planning_reason": "planner_desktop_hotkey",
                }
            ],
        ),
        (
            "在 Slack 里按回车",
            [
                {
                    "protocol": "json_fallback",
                    "tool": "app.focus_and_hotkey",
                    "input": {"app_name": "Slack", "key": "return", "modifiers": []},
                    "source": "runtime_planner",
                    "planning_reason": "planner_desktop_hotkey",
                }
            ],
        ),
        (
            "打开 Slack 后按回车",
            [
                {
                    "protocol": "json_fallback",
                    "tool": "app.open_and_hotkey",
                    "input": {"app_name": "Slack", "key": "return", "modifiers": []},
                    "source": "runtime_planner",
                    "planning_reason": "planner_desktop_hotkey",
                }
            ],
        ),
    ]

    for prompt, expected_requests in cases:
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed_tools,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.requests == expected_requests
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_app_clicks_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []
    allowed_tools = [
        "app.focus_and_click_ui_element",
        "app.open_and_click_ui_element",
        "desktop.click_ui_element",
    ]
    cases = [
        ("Slack 点搜索", "Slack", "搜索"),
        ("微信点搜索", "WeChat", "搜索"),
        ("在 Linear 上的创建按钮点击", "Linear", "创建"),
    ]

    for prompt, app_name, target in cases:
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed_tools,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert selection.requests == [
            {
                "protocol": "json_fallback",
                "tool": "app.focus_and_click_ui_element",
                "input": {
                    "app_name": app_name,
                    "target": target,
                    "role_filter": "button",
                    "click_count": 1,
                    "limit": 80,
                },
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            }
        ]
    assert legacy_calls == []


def test_planner_first_direct_selection_owns_foreground_shortcuts_before_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    def legacy_requests(prompt: str, allowed_tools: list[str]) -> list[dict[str, Any]]:
        legacy_calls.append({"prompt": prompt, "allowed_tools": list(allowed_tools)})
        if "全选复制" in prompt:
            return [
                {
                    "protocol": "json_fallback",
                    "tool": "app.open_and_safe_shortcut",
                    "input": {"app_name": "WeChat", "action": "select_all"},
                },
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "copy"},
                },
            ]
        if "最大化" in prompt:
            return [
                {
                    "protocol": "json_fallback",
                    "tool": "app.focus_and_safe_shortcut",
                    "input": {"app_name": "Google Chrome", "action": "toggle_full_screen"},
                }
            ]
        if "应用" in prompt:
            return [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "switch_next_app"},
                }
            ]
        if "go back" in prompt:
            return [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "browser_back"},
                }
            ]
        if "粘贴" in prompt:
            return [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "paste"},
                }
            ]
        if "Finder" in prompt:
            return [
                {
                    "protocol": "json_fallback",
                    "tool": "app.focus_and_safe_shortcut",
                    "input": {"app_name": "Finder", "action": "new_folder"},
                }
            ]
        return [
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_shortcut",
                "input": {"action": "next_window"},
            }
        ]

    open_shortcut_selection = planner_first_direct_tool_selection(
        "打开微信然后全选复制",
        ["desktop.list_apps", "app.open", "app.open_and_safe_shortcut", "desktop.safe_shortcut"],
        legacy_tool_requests=legacy_requests,
    )
    window_selection = planner_first_direct_tool_selection(
        "切到下一个窗口",
        ["desktop.list_apps", "app.focus", "desktop.safe_shortcut"],
        legacy_tool_requests=legacy_requests,
    )
    app_switch_selection = planner_first_direct_tool_selection(
        "切到下一个应用",
        ["desktop.list_apps", "app.focus", "desktop.safe_shortcut"],
        legacy_tool_requests=legacy_requests,
    )
    maximize_selection = planner_first_direct_tool_selection(
        "Chrome 最大化",
        ["system.volume", "app.focus_and_safe_shortcut"],
        legacy_tool_requests=legacy_requests,
    )
    browser_back_selection = planner_first_direct_tool_selection(
        "go back one page",
        ["media.system_control", "desktop.safe_shortcut"],
        legacy_tool_requests=legacy_requests,
    )
    paste_selection = planner_first_direct_tool_selection(
        "把剪贴板内容粘贴到当前输入框",
        ["clipboard.read", "desktop.safe_shortcut"],
        legacy_tool_requests=legacy_requests,
    )
    finder_selection = planner_first_direct_tool_selection(
        "Finder 新建文件夹",
        ["desktop.list_apps", "app.focus_and_safe_shortcut", "desktop.safe_shortcut"],
        legacy_tool_requests=legacy_requests,
    )

    assert open_shortcut_selection.selected_source == "runtime_planner"
    assert open_shortcut_selection.event_payload["legacy_request_count"] == 0
    assert open_shortcut_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "WeChat", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {
                "app_name": "WeChat",
                "action": "select_all",
                "selection_source": "desktop.list_apps",
                "query": "WeChat",
            },
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
    ]
    assert window_selection.selected_source == "runtime_planner"
    assert window_selection.event_payload["legacy_request_count"] == 0
    assert window_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "next_window"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert app_switch_selection.selected_source == "runtime_planner"
    assert app_switch_selection.event_payload["legacy_request_count"] == 0
    assert app_switch_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "switch_next_app"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert maximize_selection.selected_source == "runtime_planner"
    assert maximize_selection.event_payload["legacy_request_count"] == 0
    assert maximize_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "toggle_full_screen"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert browser_back_selection.selected_source == "runtime_planner"
    assert browser_back_selection.event_payload["legacy_request_count"] == 0
    assert browser_back_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "browser_back"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert paste_selection.selected_source == "runtime_planner"
    assert paste_selection.event_payload["legacy_request_count"] == 0
    assert paste_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert finder_selection.selected_source == "runtime_planner"
    assert finder_selection.event_payload["legacy_request_count"] == 0
    assert finder_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "Finder", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {
                "app_name": "Finder",
                "action": "new_folder",
                "selection_source": "desktop.list_apps",
                "query": "Finder",
            },
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert legacy_calls == []


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
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert "yachiyo_runtime_planner" not in metadata
    assert metadata["daily_desktop_tool"] == "app.open"
    assert metadata["daily_desktop_tools"] == ["app.open"]
    assert metadata["daily_desktop_source"] == "runtime_planner"
    assert metadata["daily_desktop_planning_reason"] == "planner_desktop_operation"
    assert metadata["entrypoint_plan"] is True
    assert metadata["entrypoint_plan_source"] == "runtime_planner"
    assert metadata["entrypoint_plan_reason"] == "planner_desktop_operation"
    assert metadata["entrypoint_plan_tools"] == ["app.open"]
    assert metadata["entrypoint_plan_legacy_fallback"] is False
    planner_events = [call for call in runtime.calls if call[0] == "append_run_event"]
    planner_event_types = [event[1]["event_type"] for event in planner_events]
    assert planner_event_types[:3] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.task_core.created",
    ]
    assert planner_event_types[-1] == "agent.plan.selection"
    assert planner_events[0][1]["payload"]["intent"]["inputs"]["app_name_hint"] == "PixelForge"
    selection_events = [
        event for event in planner_events if event[1]["event_type"] == "agent.plan.selection"
    ]
    assert selection_events[0][1]["payload"]["selection_source"] == "runtime_planner"
    assert selection_events[0][1]["payload"]["selected_tools"] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert selection_events[0][1]["payload"]["legacy_request_count"] == 0
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    assert [request["tool"] for request in model_loop_call[1]["direct_tool_requests"]] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]


def test_legacy_chat_task_starter_uses_runtime_execution_envelope_requests() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatPlannerEventRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)
    request = planner_enriched_chat_request(
        {
            "prompt": "打开 PixelForge",
            "metadata": {"source": "launcher", "launcher_mode": "bubble"},
        }
    )
    request["metadata"]["yachiyo_execution_envelope"]["requests"] = [
        {
            "request_id": "runtime-plan-test:request:1:desktop.inspect_app",
            "step_id": "inspect-app",
            "capability_id": "desktop.app_discovery",
            "tool_name": "desktop.inspect_app",
            "protocol": "json_fallback",
            "input": {"app_name": "PixelForge", "open_if_needed": True, "focus": True},
            "planning_reason": "planner_desktop_operation",
            "runtime_doctrine": "discover_operate_verify",
            "runtime_stage": "discover",
            "runtime_role": "inspect_ui",
            "requires_observation": True,
            "replan_triggers": ["verification_failed"],
            "replan_signal_ids": ["replan-inspect"],
            "source": "runtime_planner",
        }
    ]

    task = starter.execute_existing_main_chat_task(
        task_id="task-main",
        conversation_id="chat-1",
        prompt=str(request["prompt"]),
        metadata=request["metadata"],
    )

    assert task is not None
    start_call = [call for call in runtime.calls if call[0] == "start_main_chat_run"][0]
    assert start_call[1]["metadata"]["yachiyo_runtime_planner"] is True
    assert start_call[1]["metadata"]["source"] == "launcher"
    assert start_call[1]["runtime_execution_envelope"] == request["metadata"][
        "yachiyo_execution_envelope"
    ]
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["runtime_execution_envelope"] == request["metadata"][
        "yachiyo_execution_envelope"
    ]
    assert model_loop_call[1]["runtime_execution_metadata"]["yachiyo_runtime_planner"] is True
    assert model_loop_call[1]["runtime_execution_metadata"]["source"] == "launcher"
    direct_requests = model_loop_call[1]["direct_tool_requests"]
    assert [request["tool"] for request in direct_requests] == ["desktop.inspect_app"]
    assert direct_requests[0]["input"] == {
        "app_name": "PixelForge",
        "open_if_needed": True,
        "focus": True,
    }
    assert direct_requests[0]["step_id"] == "inspect-app"
    assert direct_requests[0]["runtime_stage"] == "discover"
    assert direct_requests[0]["runtime_role"] == "inspect_ui"
    assert direct_requests[0]["requires_observation"] is True
    assert direct_requests[0]["replan_triggers"] == ["verification_failed"]
    assert direct_requests[0]["replan_signal_ids"] == ["replan-inspect"]
    assert direct_requests[0]["capability_id"] == "desktop.app_discovery"


def test_legacy_chat_task_starter_does_not_override_runtime_planner_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_legacy_override(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("legacy parser should not run after runtime planner wins")

    monkeypatch.setattr(
        legacy_ports_module,
        "daily_desktop_entrypoint_requests",
        fail_legacy_override,
    )
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatArtifactRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)

    task = starter.execute_existing_main_chat_task(
        task_id="task-note-artifact",
        conversation_id="chat-1",
        prompt="记一下：今天要买牛奶",
    )

    assert task is not None
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    direct_requests = model_loop_call[1]["direct_tool_requests"]
    assert [request["tool"] for request in direct_requests] == ["artifact.write"]
    assert direct_requests[0]["source"] == "runtime_planner"


def test_legacy_chat_task_starter_prefers_explicit_direct_tool_requests() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatPlannerEventRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)

    task = starter.execute_existing_main_chat_task(
        task_id="task-main",
        conversation_id="chat-1",
        prompt="执行恢复动作：重新发现应用",
        direct_tool_requests=[
            {
                "tool": "desktop.list_apps",
                "input": {"query": "PixelForge", "limit": 20},
                "planning_reason": "planner_desktop_loop_auto_retry",
                "desktop_loop": {
                    "stage": "discover",
                    "retry_tool": "desktop.list_apps",
                    "can_auto_retry": True,
                },
            },
            {
                "tool": "terminal.run",
                "input": {"cmd": "echo should-not-run"},
                "approval_required": True,
            },
        ],
    )

    assert task is not None
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    direct_requests = model_loop_call[1]["direct_tool_requests"]
    assert [request["tool"] for request in direct_requests] == [
        "desktop.list_apps",
        "terminal.run",
    ]
    assert direct_requests[0]["input"] == {"query": "PixelForge", "limit": 20}
    assert direct_requests[0]["planning_reason"] == "planner_desktop_loop_auto_retry"
    assert direct_requests[0]["desktop_loop"]["can_auto_retry"] is True
    assert direct_requests[1]["approval_required"] is True
    assert model_loop_call[1]["tool_policy"] == {
        "approval_required": {"terminal.run": True}
    }


def test_legacy_chat_task_starter_promotes_direct_request_approval_policy() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatDataAnalysisRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)

    task = starter.execute_existing_main_chat_task(
        task_id="task-main",
        conversation_id="chat-1",
        prompt="运行分析脚本",
        direct_tool_requests=[
            {
                "tool": "terminal.run",
                "input": {"command": "python scripts/analyze.py"},
                "approval_required": True,
                "planning_reason": "planner_full_plan_data_analysis",
            },
        ],
    )

    assert task is not None
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    direct_requests = model_loop_call[1]["direct_tool_requests"]
    assert [request["tool"] for request in direct_requests] == ["terminal.run"]
    assert model_loop_call[1]["tool_policy"] == {
        "approval_required": {"terminal.run": True}
    }


def test_legacy_chat_task_starter_prefers_top_level_runtime_execution_envelope() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatPlannerEventRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)
    request = planner_enriched_chat_request(
        {
            "prompt": "打开 PixelForge",
            "metadata": {"source": "launcher", "launcher_mode": "bubble"},
        }
    )
    request["runtime_execution_envelope"]["requests"] = [
        {
            "request_id": "runtime-plan-test:request:1:desktop.inspect_app",
            "step_id": "inspect-app",
            "capability_id": "desktop.app_discovery",
            "tool_name": "desktop.inspect_app",
            "protocol": "json_fallback",
            "input": {"app_name": "PixelForge", "open_if_needed": True, "focus": True},
            "planning_reason": "planner_full_plan_desktop_operation",
            "runtime_stage": "discover",
            "runtime_role": "inspect_ui",
            "source": "runtime_planner",
        }
    ]
    request["metadata"]["yachiyo_execution_envelope"]["requests"] = [
        {
            "request_id": "runtime-plan-test:request:2:app.open",
            "step_id": "open-or-focus-app",
            "capability_id": "desktop.app_control",
            "tool_name": "app.open",
            "protocol": "json_fallback",
            "input": {"app_name": "PixelForge"},
            "planning_reason": "planner_desktop_operation",
            "runtime_stage": "operate",
            "source": "runtime_planner",
        }
    ]

    task = starter.execute_existing_main_chat_task(
        task_id="task-main",
        conversation_id="chat-1",
        prompt=str(request["prompt"]),
        metadata=request["metadata"],
        runtime_execution_envelope=request["runtime_execution_envelope"],
    )

    assert task is not None
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    direct_requests = model_loop_call[1]["direct_tool_requests"]
    assert [request["tool"] for request in direct_requests] == ["desktop.inspect_app"]
    assert direct_requests[0]["input"] == {
        "app_name": "PixelForge",
        "open_if_needed": True,
        "focus": True,
    }
    assert direct_requests[0]["planning_reason"] == "planner_full_plan_desktop_operation"


def test_legacy_chat_task_starter_appends_runtime_tool_progress_events() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatToolProgressRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)
    request = planner_enriched_chat_request(
        {
            "prompt": "打开 PixelForge",
            "metadata": {"source": "launcher", "launcher_mode": "bubble"},
        }
    )

    task = starter.execute_existing_main_chat_task(
        task_id="task-main",
        conversation_id="chat-1",
        prompt=str(request["prompt"]),
        metadata=request["metadata"],
        runtime_execution_envelope=request["runtime_execution_envelope"],
    )

    assert task is not None
    progress_events = [
        call[1]
        for call in runtime.calls
        if call[0] == "append_run_event"
        and call[1]["event_type"] in {
            "agent.task.todo.updated",
            "agent.task.checkpoint.updated",
        }
    ]
    assert progress_events
    todo_events = [
        event for event in progress_events
        if event["event_type"] == "agent.task.todo.updated"
    ]
    assert {event["payload"]["step_id"] for event in todo_events} >= {
        "discover-desktop-state",
        "open-or-focus-app",
        "verify-desktop-result",
    }
    latest_status_by_step = {
        event["payload"]["step_id"]: event["payload"]["status"]
        for event in todo_events
    }
    assert latest_status_by_step["discover-desktop-state"] == "completed"
    assert latest_status_by_step["open-or-focus-app"] == "completed"
    assert latest_status_by_step["verify-desktop-result"] == "completed"


def test_legacy_chat_task_starter_executes_metadata_envelope_without_selected_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.shell.yachiyo_agent import legacy_ports

    monkeypatch.setattr(
        legacy_ports,
        "planner_first_direct_tool_selection",
        lambda *_args, **_kwargs: DirectToolSelection(
            decision=None,
            requests=[],
            event_payload={
                "selection_source": "none",
                "selected_tools": [],
                "selected_reason": "no_direct_entrypoint_plan",
            },
            selected_source="none",
        ),
    )
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatPlannerEventRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)
    request = planner_enriched_chat_request(
        {
            "prompt": "打开 PixelForge",
            "metadata": {"source": "launcher", "launcher_mode": "bubble"},
        }
    )
    request["metadata"]["yachiyo_execution_envelope"]["requests"] = [
        {
            "request_id": "runtime-plan-test:request:1:app.open",
            "step_id": "open-or-focus-app",
            "capability_id": "desktop.app_control",
            "tool_name": "app.open",
            "protocol": "json_fallback",
            "input": {"app_name": "PixelForge"},
            "planning_reason": "planner_desktop_operation",
            "runtime_doctrine": "discover_operate_verify",
            "runtime_stage": "operate",
            "runtime_role": "prepare_target_app",
            "requires_post_action_verification": True,
            "source": "runtime_planner",
        }
    ]

    task = starter.execute_existing_main_chat_task(
        task_id="task-main",
        conversation_id="chat-1",
        prompt=str(request["prompt"]),
        metadata=request["metadata"],
    )

    assert task is not None
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    direct_requests = model_loop_call[1]["direct_tool_requests"]
    assert [request["tool"] for request in direct_requests] == ["app.open"]
    assert direct_requests[0]["input"] == {"app_name": "PixelForge"}
    assert direct_requests[0]["step_id"] == "open-or-focus-app"
    assert direct_requests[0]["runtime_stage"] == "operate"
    assert direct_requests[0]["requires_post_action_verification"] is True


def test_legacy_chat_task_starter_does_not_direct_run_approval_required_envelope_requests() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatPlannerEventRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)
    request = planner_enriched_chat_request(
        {
            "prompt": "打开 PixelForge",
            "metadata": {"source": "launcher", "launcher_mode": "bubble"},
        }
    )
    request["metadata"]["yachiyo_execution_envelope"]["requests"] = [
        {
            "request_id": "runtime-plan-test:request:2:terminal.run",
            "step_id": "run-analysis",
            "capability_id": "data.analysis",
            "tool_name": "terminal.run",
            "protocol": "json_fallback",
            "input": {"command": "python - <<'PY'\n# analyze data\nPY"},
            "planning_reason": "planner_full_plan_data_analysis",
            "approval_required": True,
            "source": "runtime_planner",
        }
    ]

    task = starter.execute_existing_main_chat_task(
        task_id="task-main",
        conversation_id="chat-1",
        prompt=str(request["prompt"]),
        metadata=request["metadata"],
    )

    assert task is not None
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    direct_requests = model_loop_call[1]["direct_tool_requests"]
    assert [request["tool"] for request in direct_requests] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert all(request["tool"] != "terminal.run" for request in direct_requests)
    assert all(request.get("approval_required") is not True for request in direct_requests)


def test_legacy_chat_task_starter_does_not_direct_run_top_level_approval_required_envelope() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatPlannerEventRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)
    request = planner_enriched_chat_request(
        {
            "prompt": "打开 PixelForge",
            "metadata": {"source": "launcher", "launcher_mode": "bubble"},
        }
    )
    request["runtime_execution_envelope"]["requests"] = [
        {
            "request_id": "runtime-plan-test:request:2:terminal.run",
            "step_id": "run-analysis",
            "capability_id": "data.analysis",
            "tool_name": "terminal.run",
            "protocol": "json_fallback",
            "input": {"command": "python - <<'PY'\n# analyze data\nPY"},
            "planning_reason": "planner_full_plan_data_analysis",
            "approval_required": True,
            "source": "runtime_planner",
        }
    ]
    request["metadata"]["yachiyo_execution_envelope"]["requests"] = []

    task = starter.execute_existing_main_chat_task(
        task_id="task-main",
        conversation_id="chat-1",
        prompt=str(request["prompt"]),
        metadata=request["metadata"],
        runtime_execution_envelope=request["runtime_execution_envelope"],
    )

    assert task is not None
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    direct_requests = model_loop_call[1]["direct_tool_requests"]
    assert all(request["tool"] != "terminal.run" for request in direct_requests)
    assert all(request.get("approval_required") is not True for request in direct_requests)


def test_legacy_chat_task_starter_appends_replan_for_failed_runtime_tool_result() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatToolProgressRuntime(
        {
            "event": "agent.tool.call",
            "detail": "app.open",
            "result": {
                "ok": False,
                "error": "PixelForge was not found",
            },
        }
    )
    starter = LegacyChatTaskStarter(app_runtime, runtime)
    request = planner_enriched_chat_request(
        {
            "prompt": "打开 PixelForge",
            "metadata": {"source": "launcher", "launcher_mode": "bubble"},
        }
    )

    task = starter.execute_existing_main_chat_task(
        task_id="task-main",
        conversation_id="chat-1",
        prompt=str(request["prompt"]),
        metadata=request["metadata"],
        runtime_execution_envelope=request["runtime_execution_envelope"],
    )

    assert task is not None
    appended = [
        call[1]
        for call in runtime.calls
        if call[0] == "append_run_event"
    ]
    blocked_todos = [
        event for event in appended
        if event["event_type"] == "agent.task.todo.updated"
        and event["payload"]["step_id"] == "open-or-focus-app"
    ]
    assert blocked_todos
    assert blocked_todos[-1]["payload"]["status"] == "blocked"
    replans = [
        event for event in appended
        if event["event_type"] == "agent.replan.requested"
    ]
    assert replans
    assert replans[-1]["payload"]["source_step_id"] == "open-or-focus-app"
    assert replans[-1]["payload"]["trigger"] == "tool_failure"


def test_legacy_chat_task_starter_planned_timeline_keeps_runtime_planner_sequence() -> None:
    starter = LegacyChatTaskStarter(_FakeAppRuntime(), _MainChatPlannerEventRuntime())

    timeline = starter._planner_first_planned_timeline("打开 PixelForge")

    assert [event["event"] for event in timeline] == [
        "agent.desktop.intent_planned",
        "agent.desktop.intent_planned",
        "agent.desktop.intent_planned",
    ]
    assert [event["tool"] for event in timeline] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert timeline[0]["input_preview"] == {"query": "PixelForge", "limit": 20}
    assert timeline[1]["input_preview"] == {
        "app_name": "PixelForge",
        "selection_source": "desktop.list_apps",
        "query": "PixelForge",
    }
    assert timeline[2]["input_preview"] == {}


def test_legacy_chat_task_starter_uses_generic_planner_coverage_for_legacy_timeline() -> None:
    starter = LegacyChatTaskStarter(_FakeAppRuntime(), _MainChatPlannerEventRuntime())
    metadata = {"daily_desktop_intent": True, "yachiyo_runtime_planner": True}

    app_timeline = starter._planner_first_planned_timeline("打开 PixelForge", metadata=metadata)
    media_timeline = starter._planner_first_planned_timeline(
        "打开 Spotify 搜索 Taylor Swift 并播放",
        metadata=metadata,
    )

    assert [event["tool"] for event in app_timeline] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert {event["source"] for event in app_timeline} == {"runtime_planner"}
    assert [event["tool"] for event in media_timeline] == [
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "media.music_app_open_and_play",
        "desktop.ui_elements",
    ]
    assert {event["source"] for event in media_timeline} == {"runtime_planner"}


def test_legacy_chat_task_starter_records_known_site_selection_on_runtime_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_legacy_entrypoint(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("known site opening should be owned by runtime planner")

    monkeypatch.setattr(
        legacy_ports_module,
        "daily_desktop_entrypoint_requests",
        fail_legacy_entrypoint,
    )
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
    assert metadata["daily_desktop_source"] == "runtime_planner"
    assert metadata["daily_desktop_tool"] == "browser.open_url"
    assert metadata["daily_desktop_planning_reason"] == "planner_fallback_web_research"
    assert metadata["entrypoint_plan_source"] == "runtime_planner"
    assert metadata["entrypoint_plan_tool"] == "browser.open_url"
    run_events = [call for call in runtime.calls if call[0] == "append_run_event"]
    run_event_types = [event[1]["event_type"] for event in run_events]
    assert run_event_types[:3] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.task_core.created",
    ]
    assert run_event_types[-1] == "agent.plan.selection"
    assert run_events[0][1]["payload"]["intent"]["kind"] == "web_research"
    selection_events = [
        event for event in run_events if event[1]["event_type"] == "agent.plan.selection"
    ]
    assert selection_events[0][1]["payload"]["selection_source"] == "runtime_planner"
    assert selection_events[0][1]["payload"]["legacy_request_count"] == 0
    assert selection_events[0][1]["payload"]["selected_tools"] == ["browser.open_url"]
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    direct_requests = model_loop_call[1]["direct_tool_requests"]
    assert len(direct_requests) == 1
    assert direct_requests[0]["protocol"] == "json_fallback"
    assert direct_requests[0]["tool"] == "browser.open_url"
    assert direct_requests[0]["input"] == {"url": "https://github.com"}
    assert direct_requests[0]["capability_id"] == "browser.research"
    assert direct_requests[0]["intent_kind"] == "web_research"
    assert direct_requests[0]["plan_id"].startswith("runtime-plan-")


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
    assert metadata["daily_desktop_tools"] == ["clipboard.read"]
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
    assert [request["tool"] for request in model_loop_call[1]["direct_tool_requests"]] == [
        "clipboard.read",
    ]
    assert model_loop_call[1]["direct_tool_requests"][0]["continue_to_model"] is True

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
    assert metadata["daily_desktop_tool"] == "browser.current_page"
    assert metadata["daily_desktop_tools"] == ["browser.current_page"]
    assert metadata["daily_desktop_planning_reason"] == "planner_prefetch_communication_context"
    selection_events = [
        event for event in runtime.calls if event[0] == "append_run_event"
        and event[1]["event_type"] == "agent.plan.selection"
    ]
    assert selection_events[0][1]["payload"]["selection_source"] == "runtime_planner"
    assert selection_events[0][1]["payload"]["legacy_request_count"] == 0
    assert selection_events[0][1]["payload"]["selected_tools"] == ["browser.current_page"]
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert [request["tool"] for request in model_loop_call[1]["direct_tool_requests"]] == [
        "browser.current_page"
    ]

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
    assert [request["tool"] for request in model_loop_call[1]["direct_tool_requests"]] == [
        "desktop.safe_shortcut",
        "desktop.safe_shortcut",
        "desktop.search_submit",
    ]


def test_legacy_chat_task_starter_writes_explicit_note_as_artifact_fallback() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatArtifactRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)

    task = starter.execute_existing_main_chat_task(
        task_id="task-note-artifact",
        conversation_id="chat-1",
        prompt="记一下：今天要买牛奶",
    )

    assert task is not None
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "information_capture"
    assert metadata["daily_desktop_tool"] == "artifact.write"
    assert metadata["daily_desktop_source"] == "runtime_planner"
    assert metadata["daily_desktop_planning_reason"] == (
        "planner_fallback_information_capture"
    )
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    direct_requests = model_loop_call[1]["direct_tool_requests"]
    assert len(direct_requests) == 1
    assert direct_requests[0]["protocol"] == "json_fallback"
    assert direct_requests[0]["tool"] == "artifact.write"
    assert direct_requests[0]["input"] == {
        "path": "captured-note.md",
        "content": "今天要买牛奶",
    }
    assert direct_requests[0]["source"] == "runtime_planner"
    assert direct_requests[0]["planning_reason"] == "planner_fallback_information_capture"
    assert direct_requests[0]["planner_step_id"] == "write-note-artifact"


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
    assert "yachiyo_runtime_planner" not in metadata
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
    assert "yachiyo_runtime_planner" not in metadata
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


def test_legacy_chat_task_starter_uses_spreadsheet_app_planner_sequence() -> None:
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatDataAnalysisRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)

    task = starter.execute_existing_main_chat_task(
        task_id="task-spreadsheet-data",
        conversation_id="chat-1",
        prompt="用 Excel 分析 data/sales.csv 并输出报告",
    )

    assert task is not None
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "data_analysis"
    assert metadata["daily_desktop_tool"] == "data.analyze"
    assert metadata["daily_desktop_source"] == "runtime_planner"
    assert metadata["daily_desktop_planning_reason"] == "planner_builtin_data_analysis"
    planner_events = [call for call in runtime.calls if call[0] == "append_run_event"]
    assert [
        step["tool_name"]
        for step in planner_events[1][1]["payload"]["plan"]["tool_plan"]["steps"]
    ] == ["app.open", "data.analyze"]
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    direct_requests = model_loop_call[1]["direct_tool_requests"]
    assert [request["tool"] for request in direct_requests] == ["data.analyze"]
    assert direct_requests[0]["input"] == {
        "path": "data/sales.csv",
        "artifact_path": "analysis-report.md",
        "source_kind": "csv",
        "requested_outputs": ["report"],
        "artifact_manifest": [
            {"path": "analysis-report.md", "kind": "markdown"},
        ],
    }
    assert direct_requests[0]["planning_reason"] == "planner_builtin_data_analysis"
    assert direct_requests[0]["planner_step_id"] == "analyze-data-file"


def test_legacy_chat_task_starter_uses_future_task_schedule_fallback() -> None:
    tomorrow_0900 = f"{(date.today() + timedelta(days=1)).isoformat()}T09:00"
    app_runtime = _FakeAppRuntime()
    runtime = _MainChatFutureTaskRuntime()
    starter = LegacyChatTaskStarter(app_runtime, runtime)

    task = starter.execute_existing_main_chat_task(
        task_id="task-future-reminder",
        conversation_id="chat-1",
        prompt="提醒我明天买牛奶",
    )

    assert task is not None
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "schedule"
    assert metadata["daily_desktop_tool"] == "future_task.schedule"
    assert metadata["daily_desktop_source"] == "runtime_planner"
    assert metadata["daily_desktop_planning_reason"] == "planner_fallback_schedule"
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    direct_requests = model_loop_call[1]["direct_tool_requests"]
    assert len(direct_requests) == 1
    assert direct_requests[0]["tool"] == "future_task.schedule"
    assert direct_requests[0]["input"] == {
        "title": "买牛奶",
        "prompt": "提醒用户：买牛奶。原始请求：提醒我明天买牛奶",
        "scheduled_at_epoch": datetime.fromisoformat(tomorrow_0900).timestamp(),
    }
    assert direct_requests[0]["source"] == "runtime_planner"
    assert direct_requests[0]["planning_reason"] == "planner_fallback_schedule"
    assert direct_requests[0]["planner_step_id"] == "create-schedule-item"


def test_legacy_runtime_port_readiness_includes_desktop_execution_capabilities(monkeypatch) -> None:
    runtime = _FakeRuntime()
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_permission_missing_by_capability",
        lambda: {},
    )
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_runtime_blocking_conditions_by_capability",
        lambda: {},
    )

    readiness = LegacyRuntimePort(runtime).readiness()
    capabilities = readiness["capabilities"]

    assert readiness["ok"] is True
    assert capabilities["tasks"] is True
    assert capabilities["runnables"] == 1
    assert capabilities["sandbox_provider"]["status"] == "provider_required"
    assert capabilities["sandbox_provider"]["blocking_conditions"] == [
        "sandbox_desktop_provider_required"
    ]
    assert capabilities["desktop_provider_ready"] is False
    assert capabilities["desktop_provider_supported_tools"] == []
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
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_runtime_blocking_conditions_by_capability",
        lambda: {},
    )

    readiness = LegacyRuntimePort(runtime).readiness()
    capabilities = readiness["capabilities"]

    assert capabilities["screen_capture"]["missing_permissions"] == ["screen_recording"]
    assert capabilities["screen_capture"]["available"] is False
    assert capabilities["foreground_input"]["missing_permissions"] == ["accessibility"]
    assert capabilities["foreground_input"]["available"] is False
    assert runtime.calls == [("list_runnables", None)]


def test_legacy_runtime_port_readiness_reports_sandbox_provider_health(
    monkeypatch,
) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"ok": true, "status": "ready", "supported_tools": '
                b'["desktop.list_apps"]}'
            )

        def getcode(self) -> int:
            return self.status

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        return FakeResponse()

    runtime = _FakeRuntime()
    monkeypatch.setattr(
        "apps.shell.agent.runtime.desktop_execution_providers.urlopen_with_bundled_ca",
        fake_urlopen,
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", "http://127.0.0.1:19091")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_ID", "local-headless-desktop")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS", "desktop.list_apps")
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_permission_missing_by_capability",
        lambda: {},
    )
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_runtime_blocking_conditions_by_capability",
        lambda: {},
    )

    readiness = LegacyRuntimePort(runtime).readiness()
    capabilities = readiness["capabilities"]

    assert capabilities["desktop_provider_ready"] is True
    assert capabilities["desktop_provider_supported_tools"] == ["desktop.list_apps"]
    assert capabilities["sandbox_provider"]["status"] == "available"
    assert capabilities["sandbox_provider"]["health"]["checked"] is True
    assert capabilities["sandbox_provider"]["health"]["status"] == "ready"


def test_legacy_runtime_port_readiness_reports_desktop_runtime_blockers(monkeypatch) -> None:
    runtime = _FakeRuntime()
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_permission_missing_by_capability",
        lambda: {},
    )
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_runtime_blocking_conditions_by_capability",
        lambda: {
            "desktop_execution": ["desktop_session_locked"],
            "active_window": ["desktop_session_locked"],
        },
    )

    readiness = LegacyRuntimePort(runtime).readiness()
    capabilities = readiness["capabilities"]

    assert capabilities["desktop_execution"]["available"] is False
    assert capabilities["desktop_execution"]["missing_permissions"] == []
    assert capabilities["desktop_execution"]["blocking_conditions"] == [
        "desktop_session_locked"
    ]
    assert capabilities["active_window"]["blocking_conditions"] == [
        "desktop_session_locked"
    ]
    assert runtime.calls == [("list_runnables", None)]


def test_legacy_runtime_port_readiness_reports_foreground_activation_blocker(monkeypatch) -> None:
    runtime = _FakeRuntime()
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_permission_missing_by_capability",
        lambda: {},
    )
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_runtime_blocking_conditions_by_capability",
        lambda: {
            "foreground_activation": ["foreground_focus_unavailable"],
        },
    )

    readiness = LegacyRuntimePort(runtime).readiness()
    capabilities = readiness["capabilities"]

    assert capabilities["foreground_activation"]["available"] is False
    assert capabilities["foreground_activation"]["missing_permissions"] == []
    assert capabilities["foreground_activation"]["blocking_conditions"] == [
        "foreground_focus_unavailable"
    ]
    assert "app.open" in capabilities["app_control"]["available_tools"]
    assert "app.focus" in capabilities["app_control"]["unavailable_tools"]
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
    create_call = next(call for call in runtime.calls if call[0] == "create_workflow_run")
    assert create_call[1]["workflow_id"] == "workflow-1"
    assert create_call[1]["user_goal"] == "Build report"
    assert create_call[1]["source"] == "yachiyo_chat"
    assert create_call[1]["client_run_id"] == "task-workflow-1"
    assert create_call[1]["runtime_planner_entrypoint"] is True
    assert create_call[1]["daily_desktop_planning_context"] == "Build report"
    assert create_call[1]["metadata"]["yachiyo_runtime_planner"] is True
    assert create_call[1]["runtime_execution_envelope"]["intent_kind"] == "code_task"
    assert [request["tool"] for request in create_call[1]["direct_tool_requests"]] == [
        "workspace.list",
    ]
    assert (
        "link_task_run",
        {"task_id": "task-workflow-1", "run_id": "workflow-run-1", "session_id": "chat-1"},
    ) in runtime.calls


def test_legacy_runtime_port_starts_and_links_chat_group_task() -> None:
    runtime = _FakeRuntime()

    task = LegacyRuntimePort(runtime).start_chat_task(
        {
            "prompt": "一起整理调研结论",
            "conversation_id": "chat-1",
            "client_task_id": "task-group-1",
            "group_id": "group-1",
        }
    )

    create_call = next(
        call for call in runtime.calls if call[0] == "create_run_for_runnable_async"
    )
    assert task["task_id"] == "task-group-1"
    assert task["conversation_id"] == "chat-1"
    assert task["metadata"]["runnable_kind"] == "group"
    assert task["metadata"]["group_id"] == "group-1"
    assert task["metadata"]["run_group_id"] == "group-run-1"
    assert task["status"] == "approval_required"
    assert task["open_in_studio_url"] == "#/agents?run_id=run-1&group_run=group-run-1"
    assert create_call[1]["runnable_id"] == "agent-1"
    assert create_call[1]["user_goal"] == "一起整理调研结论"
    assert create_call[1]["runtime_planner_entrypoint"] is True
    assert create_call[1]["daily_desktop_planning_context"] == "一起整理调研结论"
    assert (
        "link_task_run",
        {"task_id": "task-group-1", "run_id": "run-1", "session_id": "chat-1"},
    ) in runtime.calls


def test_legacy_runtime_port_aggregates_group_run_chat_task_timeline() -> None:
    runtime = _EventStoreFakeRuntime()
    runtime.runs["run-1"]["artifacts"] = [
        {
            "artifact_id": "artifact-group-1",
            "kind": "markdown",
            "path": "team-plan.md",
        }
    ]
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "一起整理调研结论",
            "conversation_id": "chat-1",
            "client_task_id": "task-group-1",
            "group_id": "group-1",
        }
    )

    task = port.get_task_snapshot("task-group-1")
    timeline = port.get_task_timeline("task-group-1")
    page = port.get_task_event_page("task-group-1", after_sequence=0, limit=1)

    task_event_types = [event.get("event_type") or event.get("event") for event in task["recent_events"]]
    timeline_event_types = [
        event.get("event_type") or event.get("event")
        for event in timeline["events"]
    ]
    assert task["metadata"]["runnable_kind"] == "group"
    assert task["metadata"]["group_id"] == "group-1"
    assert task["metadata"]["run_group_id"] == "group-run-1"
    assert task["pending_approvals"][0]["approval_id"] == "approval-1"
    assert task["artifacts"][0]["path"] == "team-plan.md"
    assert task["artifacts"][0]["source_run_id"] == "run-1"
    assert "group.run.started" in task_event_types
    assert "group.member.started" in task_event_types
    assert "group.run.started" in timeline_event_types
    assert timeline["run_group_id"] == "group-run-1"
    assert page["run_id"] == "group-run-1"
    assert page["events"][0]["event_type"] == "group.run.started"


def test_legacy_runtime_port_routes_group_task_approval_to_matching_child_run() -> None:
    runtime = _EventStoreFakeRuntime()
    runtime.group_child_run_ids = ["run-1", "run-2"]
    runtime.runs["run-1"]["pending_approval"] = None
    runtime.runs["run-2"] = {
        "run_id": "run-2",
        "run_group_id": "group-run-1",
        "user_goal": "一起整理调研结论",
        "status": "approval_required",
        "pending_approval": {"approval_id": "approval-2", "tool": "terminal.run"},
        "timeline": [{"event": "run.started"}],
    }
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "一起整理调研结论",
            "conversation_id": "chat-1",
            "client_task_id": "task-group-1",
            "group_id": "group-1",
        }
    )
    runtime.calls.clear()

    approved = port.approve("task-group-1", {"approval_id": "approval-2"})

    assert ("approve_run_approval", "run-2") in runtime.calls
    assert approved["task_id"] == "task-group-1"


def test_legacy_runtime_port_reads_group_task_artifact_from_source_child_run() -> None:
    runtime = _EventStoreFakeRuntime()
    runtime.group_child_run_ids = ["run-1", "run-2"]
    runtime.runs["run-2"] = {
        "run_id": "run-2",
        "run_group_id": "group-run-1",
        "user_goal": "一起整理调研结论",
        "status": "completed",
        "artifacts": [
            {
                "artifact_id": "artifact-group-2",
                "kind": "markdown",
                "path": "review.md",
            }
        ],
        "timeline": [{"event": "run.started"}],
    }
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "一起整理调研结论",
            "conversation_id": "chat-1",
            "client_task_id": "task-group-1",
            "group_id": "group-1",
        }
    )
    runtime.calls.clear()

    artifact = port.read_task_artifact("task-group-1", "review.md")

    assert artifact["run_id"] == "run-2"
    assert artifact["task_id"] == "task-group-1"
    assert artifact["run_group_id"] == "group-run-1"
    assert (
        "read_run_artifact",
        {"run_id": "run-2", "artifact_path": "review.md"},
    ) in runtime.calls


def test_legacy_runtime_port_aggregates_workflow_child_debug_state_for_chat_task() -> None:
    runtime = _EventStoreFakeRuntime()
    runtime.group_child_run_ids = ["workflow-run-1", "workflow-child-1"]
    runtime.runs["workflow-run-1"]["run_group_id"] = "workflow-group-1"
    runtime.runs["workflow-run-1"]["pending_approval"] = None
    runtime.runs["workflow-run-1"]["timeline"] = [
        {
            "event_type": "workflow.run.started",
            "sequence": 1,
            "payload": {
                "workflow_id": "workflow-1",
                "workflow_run_id": "workflow-run-1",
            },
        },
        {
            "event_type": "workflow.node.agent",
            "sequence": 2,
            "payload": {
                "child_run_id": "workflow-child-1",
                "workflow_id": "workflow-1",
                "workflow_run_id": "workflow-run-1",
                "workflow_node_id": "analyze",
                "workflow_node_label": "Analyze data",
            },
        },
    ]
    runtime.runs["workflow-child-1"] = {
        "run_id": "workflow-child-1",
        "kind": "agent_run",
        "runnable_id": "agent-1",
        "run_group_id": "workflow-group-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_id": "workflow-1",
        "user_goal": "Analyze data",
        "status": "approval_required",
        "pending_approval": {
            "approval_id": "approval-child-1",
            "tool": "terminal.run",
        },
        "artifacts": [
            {
                "artifact_id": "artifact-workflow-child",
                "kind": "markdown",
                "path": "analysis.md",
            }
        ],
        "timeline": [
            {
                "event_type": "artifact.created",
                "sequence": 1,
                "payload": {
                    "artifact_id": "artifact-workflow-child",
                    "kind": "markdown",
                    "path": "analysis.md",
                },
            },
            {
                "event_type": "agent.tool.approval_required",
                "sequence": 2,
                "payload": {
                    "approval_id": "approval-child-1",
                    "tool_name": "terminal.run",
                    "title": "Run analysis",
                },
            },
        ],
    }
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Build report",
            "conversation_id": "chat-1",
            "client_task_id": "task-workflow-1",
            "workflow_id": "workflow-1",
        }
    )

    task = port.get_task_snapshot("task-workflow-1")
    timeline = port.get_task_timeline("task-workflow-1")
    page = port.get_task_event_page("task-workflow-1", after_sequence=0, limit=20)
    workflow_events = timeline["events"]
    child_approval_events = [
        event
        for event in workflow_events
        if event.get("event_type") == "workflow.run.tool.approval_required"
    ]

    assert task["metadata"]["runnable_kind"] == "workflow"
    assert task["metadata"]["workflow_run_id"] == "workflow-run-1"
    assert task["status"] == "approval_required"
    assert task["pending_approvals"][0]["approval_id"] == "approval-child-1"
    assert task["artifacts"][0]["path"] == "analysis.md"
    assert task["artifacts"][0]["source_run_id"] == "workflow-child-1"
    assert timeline["children"][0]["run_id"] == "workflow-child-1"
    assert timeline["children"][0]["workflow_node_id"] == "analyze"
    assert timeline["pending_approval"]["run_id"] == "workflow-child-1"
    assert timeline["artifacts"][0]["source_run_id"] == "workflow-child-1"
    assert child_approval_events
    assert child_approval_events[0]["run_id"] == "workflow-run-1"
    assert child_approval_events[0]["payload"]["source_run_id"] == "workflow-child-1"
    assert child_approval_events[0]["payload"]["workflow_node_id"] == "analyze"
    assert page["run_id"] == "workflow-run-1"
    assert page["workflow_run_id"] == "workflow-run-1"
    assert "workflow.run.tool.approval_required" in [
        event.get("event_type") for event in page["events"]
    ]


def test_legacy_runtime_port_routes_workflow_task_approval_and_artifact_to_child_run() -> None:
    runtime = _EventStoreFakeRuntime()
    runtime.group_child_run_ids = ["workflow-run-1", "workflow-child-1"]
    runtime.runs["workflow-run-1"]["run_group_id"] = "workflow-group-1"
    runtime.runs["workflow-run-1"]["pending_approval"] = None
    runtime.runs["workflow-run-1"]["timeline"] = [
        {
            "event_type": "workflow.node.agent",
            "sequence": 1,
            "payload": {
                "child_run_id": "workflow-child-1",
                "workflow_id": "workflow-1",
                "workflow_run_id": "workflow-run-1",
                "workflow_node_id": "analyze",
                "workflow_node_label": "Analyze data",
            },
        }
    ]
    runtime.runs["workflow-child-1"] = {
        "run_id": "workflow-child-1",
        "kind": "agent_run",
        "runnable_id": "agent-1",
        "run_group_id": "workflow-group-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_id": "workflow-1",
        "user_goal": "Analyze data",
        "status": "approval_required",
        "pending_approval": {
            "approval_id": "approval-child-1",
            "tool": "terminal.run",
        },
        "artifacts": [
            {
                "artifact_id": "artifact-workflow-child",
                "kind": "markdown",
                "path": "analysis.md",
            }
        ],
        "timeline": [{"event": "run.started"}],
    }
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Build report",
            "conversation_id": "chat-1",
            "client_task_id": "task-workflow-1",
            "workflow_id": "workflow-1",
        }
    )
    runtime.calls.clear()

    approved = port.approve("task-workflow-1", {"approval_id": "approval-child-1"})
    artifact = port.read_task_artifact("task-workflow-1", "analysis.md")

    assert ("approve_run_approval", "workflow-child-1") in runtime.calls
    assert approved["task_id"] == "task-workflow-1"
    assert approved["metadata"]["workflow_run_id"] == "workflow-run-1"
    assert artifact["run_id"] == "workflow-child-1"
    assert artifact["workflow_run_id"] == "workflow-run-1"
    assert (
        "read_run_artifact",
        {"run_id": "workflow-child-1", "artifact_path": "analysis.md"},
    ) in runtime.calls


def test_legacy_runtime_port_forwards_runtime_execution_plan_to_workflow_run() -> None:
    runtime = _FakeRuntime()
    request = planner_enriched_chat_request(
        {
            "prompt": "请分析 data/sales.csv 并输出报告",
            "conversation_id": "chat-1",
            "client_task_id": "task-workflow-1",
            "workflow_id": "workflow-1",
        }
    )

    task = LegacyRuntimePort(runtime).start_chat_task(request)

    create_call = next(
        payload
        for call_name, payload in runtime.calls
        if call_name == "create_workflow_run"
    )
    direct_requests = create_call["direct_tool_requests"]
    assert task["task_id"] == "task-workflow-1"
    assert create_call["runtime_planner_entrypoint"] is True
    assert create_call["daily_desktop_planning_context"] == "请分析 data/sales.csv 并输出报告"
    assert create_call["runtime_execution_envelope"] == request["runtime_execution_envelope"]
    assert create_call["metadata"]["yachiyo_runtime_planner"] is True
    assert create_call["metadata"]["yachiyo_execution_envelope"] == (
        request["metadata"]["yachiyo_execution_envelope"]
    )
    assert [request["tool"] for request in direct_requests] == [
        "workspace.read",
        "python.run",
        "artifact.write",
    ]
    assert direct_requests[1]["approval_required"] is True


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


def test_legacy_runtime_port_merges_runtime_event_store_into_task_payloads() -> None:
    runtime = _EventStoreFakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "分析 sales.csv 并输出报告",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )
    task_core_event = next(
        event
        for event in runtime.event_store["run-1"]
        if event["event_type"] == "agent.task_core.created"
    )
    task_core = task_core_event["payload"]["task_core"]
    todo = task_core["todos"][0]
    runtime.append_run_event(
        "run-1",
        "agent.task.todo.updated",
        {
            "todo_id": todo["todo_id"],
            "step_id": todo["step_id"],
            "status": "completed",
            "todo": {**todo, "status": "completed"},
        },
    )

    task = port.get_task_snapshot("task-1")
    timeline = port.get_task_timeline("task-1")

    task_event_types = [
        event.get("event") or event.get("event_type")
        for event in task["recent_events"]
    ]
    timeline_event_types = [
        event.get("event") or event.get("event_type")
        for event in timeline["events"]
    ]
    assert task_event_types[:5] == [
        "run.started",
        "agent.intent.selected",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.plan.step",
    ]
    assert "agent.task.todo.updated" in task_event_types
    assert timeline_event_types[:5] == [
        "run.started",
        "agent.intent.selected",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.plan.step",
    ]
    assert "agent.task.todo.updated" in timeline_event_types


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
    runtime.calls.clear()

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


def test_legacy_studio_port_starts_agent_run_with_daily_desktop_overlay() -> None:
    runtime = _StudioStartRuntime()
    run = LegacyStudioPort(runtime).start_agent_run(
        {
            "agent_id": "agent-1",
            "objective": "打开 PixelForge",
            "client_run_id": "studio-run-1",
        }
    )

    assert run["run_id"] == "studio-agent-run-1"
    assert runtime.calls[0] == (
        "create_agent_run",
        {
            "agent_id": "agent-1",
            "user_goal": "打开 PixelForge",
            "source": "yachiyo_studio",
            "client_run_id": "studio-run-1",
            "run_group_id": None,
            "daily_desktop_policy_overlay": True,
            "runtime_planner_entrypoint": True,
        },
    )


def test_legacy_studio_port_start_workflow_run_returns_runtime_events() -> None:
    runtime = _StudioStartRuntime()
    run = LegacyStudioPort(runtime).start_workflow_run(
        {
            "workflow_id": "workflow-1",
            "objective": "分析 sales.csv 并输出报告",
            "client_run_id": "studio-workflow-run-1",
        }
    )

    event_types = [event.get("event_type") or event.get("event") for event in run["events"]]
    assert run["run_id"] == "studio-workflow-run-1"
    assert event_types[:5] == [
        "workflow.run.started",
        "agent.intent.selected",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.plan.step",
    ]
    assert (
        "create_workflow_run",
        {
            "workflow_id": "workflow-1",
            "user_goal": "分析 sales.csv 并输出报告",
            "source": "yachiyo_studio",
            "client_run_id": "studio-workflow-run-1",
            "run_group_id": None,
        },
    ) in runtime.calls


class _StudioStartRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.run_events: dict[str, list[dict[str, Any]]] = {
            "studio-workflow-run-1": [
                {"event_type": "workflow.run.started", "sequence": 1},
            ],
        }

    def create_agent_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_agent_run", payload))
        return {
            "run_id": "studio-agent-run-1",
            "kind": "agent_run",
            "status": "running",
            "timeline": [],
        }

    def create_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_workflow_run", payload))
        return {
            "run_id": "studio-workflow-run-1",
            "kind": "workflow_run",
            "workflow_run_id": "studio-workflow-run-1",
            "workflow_id": payload.get("workflow_id"),
            "status": "running",
            "timeline": [{"event_type": "workflow.run.started", "sequence": 1}],
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
        events = self.run_events.setdefault(run_id, [])
        events.append(
            {
                "event_type": event_type,
                "sequence": len(events) + 1,
                "payload": dict(payload),
            }
        )

    def list_run_events(
        self,
        run_id: str,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(("list_run_events", run_id))
        return {"events": list(self.run_events.get(run_id, []))}

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return {
            "agent_id": agent_id,
            "tool_policy": {"allowed_tools": ["workspace.read"], "approval_required": {}},
        }


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
        self.group_child_run_ids = ["run-1"]

    def list_runnables(self) -> dict[str, Any]:
        self.calls.append(("list_runnables", None))
        return {"runnables": [{"id": "builtin:yachiyo-main"}]}

    def create_run_for_runnable_async(self, **payload: Any) -> dict[str, Any]:
        self.calls.append(("create_run_for_runnable_async", payload))
        run = dict(self.runs["run-1"])
        if "run_group_id" in payload:
            run["run_group_id"] = payload.get("run_group_id") or "group-run-1"
        self.runs["run-1"] = dict(run)
        return run

    def create_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_workflow_run", payload))
        return dict(self.runs["workflow-run-1"])

    def get_run(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run", run_id))
        return dict(self.runs[run_id])

    def list_run_events(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("list_run_events", run_id))
        return {"events": list(self.runs[run_id]["timeline"])}

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return {
            "agent_id": agent_id,
            "name": agent_id,
            "tool_policy": {"allowed_tools": ["workspace.read"], "approval_required": {}},
        }

    def get_agent_group(self, group_id: str) -> dict[str, Any]:
        self.calls.append(("get_agent_group", group_id))
        return {
            "group_id": group_id,
            "name": "Research Team",
            "members": [{"agent_id": "agent-1", "name": "Planner"}],
            "mode": "parallel",
            "memory_scope": "shared",
        }

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        self.calls.append(("get_run_group", run_group_id))
        return {
            "run_group_id": run_group_id,
            "title": "Research Team",
            "status": "running",
            "summary": "",
            "child_run_ids": list(self.group_child_run_ids),
        }

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


class _EventStoreFakeRuntime(_FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.event_store: dict[str, list[dict[str, Any]]] = {}

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
        events = self.event_store.setdefault(run_id, [])
        events.append(
            {
                "event_type": event_type,
                "sequence": len(events) + 2,
                "payload": dict(payload),
            }
        )

    def list_run_events(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("list_run_events", run_id))
        return {
            "events": [
                *list(self.runs[run_id]["timeline"]),
                *list(self.event_store.get(run_id, [])),
            ]
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
        metadata: dict[str, Any] | None = None,
        runtime_execution_envelope: dict[str, Any] | None = None,
        direct_tool_request: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "start_main_chat_run",
                {
                    "task_id": task_id,
                    "session_id": session_id,
                    "user_goal": user_goal,
                    "metadata": metadata,
                    "runtime_execution_envelope": runtime_execution_envelope,
                    "direct_tool_request": direct_tool_request,
                    "direct_tool_requests": direct_tool_requests,
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
        runtime_execution_envelope: dict[str, Any] | None = None,
        runtime_execution_metadata: dict[str, Any] | None = None,
        tool_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "execute_main_chat_model_loop",
                {
                    "run_id": run_id,
                    "messages": messages,
                    "direct_tool_request": direct_tool_request,
                    "direct_tool_requests": direct_tool_requests,
                    "runtime_execution_envelope": runtime_execution_envelope,
                    "runtime_execution_metadata": runtime_execution_metadata,
                    "tool_policy": tool_policy,
                },
            )
        )
        return {"run_id": run_id, "status": "completed", "result": "Done"}

    def complete_main_chat_run(self, run_id: str, result: str) -> dict[str, Any]:
        self.calls.append(("complete_main_chat_run", {"run_id": run_id, "result": result}))
        return {"run_id": run_id, "status": "completed", "result": result}


class _MainChatToolProgressRuntime(_MainChatPlannerEventRuntime):
    def __init__(self, *tool_events: dict[str, Any]) -> None:
        super().__init__()
        self.tool_events = list(tool_events) or [
            {
                "event": "agent.tool.call",
                "detail": "desktop.list_apps",
                "result": {"ok": True, "count": 1},
            },
            {
                "event": "agent.tool.call",
                "detail": "app.open",
                "result": {"ok": True, "app_name": "PixelForge"},
            },
            {
                "event": "agent.tool.call",
                "detail": "desktop.active_window",
                "result": {"ok": True, "app_name": "PixelForge"},
            },
        ]

    def execute_main_chat_model_loop(
        self,
        run_id: str,
        messages: list[dict[str, Any]],
        *,
        direct_tool_request: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
        tool_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "execute_main_chat_model_loop",
                {
                    "run_id": run_id,
                    "messages": messages,
                    "direct_tool_request": direct_tool_request,
                    "direct_tool_requests": direct_tool_requests,
                    "tool_policy": tool_policy,
                },
            )
        )
        return {
            "run_id": run_id,
            "status": "completed",
            "result": "Done",
            "timeline": [dict(event) for event in self.tool_events],
        }


class _MainChatDataAnalysisRuntime(_MainChatPlannerEventRuntime):
    def _main_chat_tool_policy(self) -> dict[str, Any]:
        return {
            "allowed_tools": [
                "app.open",
                "data.analyze",
                "workspace.read",
                "terminal.run",
                "artifact.write",
            ],
            "approval_required": {},
        }


class _MainChatFutureTaskRuntime(_MainChatPlannerEventRuntime):
    def _main_chat_tool_policy(self) -> dict[str, Any]:
        return {
            "allowed_tools": ["future_task.schedule"],
            "approval_required": {"future_task.schedule": True},
        }


class _MainChatArtifactRuntime(_MainChatPlannerEventRuntime):
    def _main_chat_tool_policy(self) -> dict[str, Any]:
        return {
            "allowed_tools": ["artifact.write"],
            "approval_required": {},
        }
