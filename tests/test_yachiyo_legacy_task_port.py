"""Legacy Chat task runtime port adapter tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.yachiyo_agent.daily_desktop import daily_desktop_allowed_tools
from apps.shell.yachiyo_agent.legacy_ports import (
    LegacyChatTaskStarter,
    LegacyRuntimePort as CompatLegacyRuntimePort,
)
from apps.shell.yachiyo_agent.legacy_tasks import LegacyRuntimePort
from apps.shell.yachiyo_agent.entrypoint_tool_selection import planner_first_direct_tool_selection


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
            ["desktop.safe_shortcut", "app.open", "desktop.safe_shortcut", "desktop.safe_shortcut"],
        ),
        (
            "把当前网页链接加入日历",
            ["desktop.safe_shortcut", "app.open", "desktop.safe_shortcut", "desktop.safe_shortcut"],
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
        ("微信关闭窗口", ["app.focus", "desktop.close_window", "desktop.active_window"]),
        (
            "在 VS Code 里执行命令 Format Document",
            [
                "app.focus",
                "desktop.safe_shortcut",
                "desktop.safe_type_text",
                "desktop.submit_foreground",
                "desktop.ui_elements",
            ],
        ),
        (
            "Finder look for Downloads",
            [
                "app.focus",
                "desktop.safe_shortcut",
                "desktop.safe_type_text",
                "desktop.search_submit",
                "desktop.ui_elements",
            ],
        ),
        ("微信打开搜索", ["app.focus", "desktop.safe_shortcut", "desktop.ui_elements"]),
        ("Chrome 点登录", ["app.focus_and_click_ui_element", "desktop.ui_elements"]),
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
    prompts = (
        "微信关闭窗口",
        "在 VS Code 里执行命令 Format Document",
        "把当前网页链接粘贴到 Slack",
        "在 Slack 粘贴当前网页链接",
        "复制当前网页内容",
        "把选中的内容填到当前输入框",
        "把当前网页链接输入到地址栏",
        "把当前页面内容输入到搜索框",
        "把当前网页链接输入到 Slack 搜索框",
        "把当前页面内容输入到 Slack 搜索框",
        "打开 Slack 搜索框输入选中的内容",
        "Finder look for Downloads",
        "微信打开搜索",
        "Chrome 点登录",
        "把当前网页链接加入提醒事项",
        "把当前网页链接加入日历",
        "创建备忘录",
    )

    remaining_legacy_prompts: list[str] = []
    for prompt in prompts:
        selection = planner_first_direct_tool_selection(
            prompt,
            daily_desktop_allowed_tools(),
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )
        if selection.selected_source != "runtime_planner":
            remaining_legacy_prompts.append(prompt)

    assert remaining_legacy_prompts == []
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
            "tool": "app.open",
            "input": {"app_name": "PixelForge"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert chinese_app_selection.selected_source == "runtime_planner"
    assert chinese_app_selection.event_payload["legacy_request_count"] == 0
    assert chinese_app_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
    assert focus_selection.selected_source == "runtime_planner"
    assert focus_selection.event_payload["legacy_request_count"] == 0
    assert focus_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Slack"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        }
    ]
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
        assert selection.requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": tool_input,
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.running_apps",
                "input": {},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            },
        ]
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
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
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
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "select_all"},
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
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "new_folder"},
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
    assert app_runtime.chat_session.metadata_calls[0]["metadata"]["yachiyo_runtime_planner"] is True
    assert app_runtime.chat_session.metadata_calls[0]["metadata"]["yachiyo_intent_kind"] == (
        "desktop_operation"
    )
    metadata = app_runtime.chat_session.metadata_calls[0]["metadata"]
    assert metadata["daily_desktop_tool"] == "app.open"
    assert metadata["daily_desktop_tools"] == ["app.open"]
    assert metadata["daily_desktop_source"] == "daily_desktop_intent"
    assert metadata["daily_desktop_planning_reason"] == "clear_daily_desktop_intent"
    assert metadata["entrypoint_plan"] is True
    assert metadata["entrypoint_plan_source"] == "daily_desktop_intent"
    assert metadata["entrypoint_plan_reason"] == "clear_daily_desktop_intent"
    assert metadata["entrypoint_plan_tools"] == ["app.open"]
    assert metadata["entrypoint_plan_legacy_fallback"] is True
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
    assert selection_events[0][1]["payload"]["selected_tools"] == [
        "app.open",
        "desktop.active_window",
    ]
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    assert [request["tool"] for request in model_loop_call[1]["direct_tool_requests"]] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]


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
    assert timeline[1]["input_preview"] == {"app_name": "PixelForge"}
    assert timeline[2]["input_preview"] == {}


def test_legacy_chat_task_starter_records_known_site_selection_on_runtime_planner() -> None:
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
    assert [event[1]["event_type"] for event in run_events[:2]] == [
        "agent.intent.selected",
        "agent.plan.created",
    ]
    assert run_events[0][1]["payload"]["intent"]["kind"] == "web_research"
    selection_events = [
        event for event in run_events if event[1]["event_type"] == "agent.plan.selection"
    ]
    assert selection_events[0][1]["payload"]["selection_source"] == "runtime_planner"
    assert selection_events[0][1]["payload"]["legacy_request_count"] == 0
    assert selection_events[0][1]["payload"]["planner_tools"] == ["browser.open_url"]
    assert selection_events[0][1]["payload"]["selected_tools"] == ["browser.open_url"]
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    assert model_loop_call[1]["direct_tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://github.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]


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
        "app.focus",
        "desktop.safe_shortcut",
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
        "app.focus",
        "desktop.safe_shortcut",
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
    assert model_loop_call[1]["direct_tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "artifact.write",
            "input": {
                "path": "captured-note.md",
                "content": "今天要买牛奶",
            },
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_information_capture",
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
    assert metadata["daily_desktop_tool"] == "app.open"
    assert metadata["daily_desktop_source"] == "runtime_planner"
    assert metadata["daily_desktop_planning_reason"] == (
        "planner_fallback_data_analysis_spreadsheet_app"
    )
    planner_events = [call for call in runtime.calls if call[0] == "append_run_event"]
    assert [
        step["tool_name"]
        for step in planner_events[1][1]["payload"]["plan"]["tool_plan"]["steps"]
    ] == ["app.open", "data.analyze"]
    model_loop_call = [
        call for call in runtime.calls if call[0] == "execute_main_chat_model_loop"
    ][0]
    assert model_loop_call[1]["direct_tool_request"] is None
    assert model_loop_call[1]["direct_tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Microsoft Excel"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_data_analysis_spreadsheet_app",
        },
        {
            "protocol": "json_fallback",
            "tool": "data.analyze",
            "input": {
                "path": "data/sales.csv",
                "artifact_path": "analysis-report.md",
                "source_kind": "csv",
                "requested_outputs": ["report"],
                "artifact_manifest": [
                    {"path": "analysis-report.md", "kind": "markdown"},
                ],
            },
            "source": "runtime_planner",
            "planning_reason": "planner_builtin_data_analysis",
        },
    ]


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
    assert model_loop_call[1]["direct_tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "future_task.schedule",
            "input": {
                "title": "买牛奶",
                "prompt": "提醒用户：买牛奶。原始请求：提醒我明天买牛奶",
                "scheduled_at_epoch": datetime.fromisoformat(tomorrow_0900).timestamp(),
            },
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_schedule",
        }
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
