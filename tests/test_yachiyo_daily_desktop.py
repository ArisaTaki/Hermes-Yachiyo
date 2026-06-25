"""Shared daily desktop runtime helper tests."""

from __future__ import annotations

from apps.shell.yachiyo_agent.daily_desktop import (
    daily_desktop_direct_metadata_request,
    daily_desktop_entrypoint_requests,
    daily_desktop_planned_timeline,
    daily_desktop_recovery_execution_prompt,
    daily_desktop_user_metadata,
)


def test_daily_desktop_entrypoint_requests_project_shared_metadata_and_timeline() -> None:
    requests = daily_desktop_entrypoint_requests("可以帮我打开 Word 吗")

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Microsoft Word"},
        }
    ]
    assert daily_desktop_user_metadata(requests) == {
        "daily_desktop_intent": True,
        "daily_desktop_source": "daily_desktop_intent",
        "daily_desktop_planning_reason": "clear_daily_desktop_intent",
        "daily_desktop_tool": "app.open",
        "daily_desktop_tools": ["app.open"],
    }
    assert daily_desktop_planned_timeline(requests=requests) == [
        {
            "event": "agent.desktop.intent_planned",
            "detail": "app.open",
            "tool": "app.open",
            "status": "planned",
            "source": "daily_desktop_intent",
            "planning_reason": "clear_daily_desktop_intent",
            "input_preview": {"app_name": "Microsoft Word"},
        }
    ]


def test_daily_desktop_entrypoint_routes_polite_app_open_questions_to_desktop_tool() -> None:
    cases = (
        ("你能帮我打开微信吗", "WeChat"),
        ("你能启动一下备忘录吗", "Notes"),
        ("Could you launch Calendar for me?", "Calendar"),
        ("Would you open Notes please?", "Notes"),
    )

    for prompt, app_name in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "app.open",
                "input": {"app_name": app_name},
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == "app.open"


def test_daily_desktop_entrypoint_routes_polite_focus_and_show_questions_to_desktop_tools() -> None:
    cases = (
        ("你能帮我切到Chrome吗", "app.focus", {"app_name": "Google Chrome"}),
        ("你可以帮我聚焦Chrome吗", "app.focus", {"app_name": "Google Chrome"}),
        ("你能帮我显示Finder吗", "app.show", {"app_name": "Finder"}),
        ("你能帮我还原微信吗", "app.show", {"app_name": "WeChat"}),
    )

    for prompt, tool_name, tool_input in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == tool_name


def test_daily_desktop_entrypoint_routes_current_app_window_control_to_desktop_tools() -> None:
    cases = (
        ("你可以帮我隐藏一下前台应用吗", "desktop.hide_app", {}),
        ("Can you hide the current app?", "desktop.hide_app", {}),
        ("Could you hide the foreground app please?", "desktop.hide_app", {}),
        ("你能帮我收起一下当前应用吗", "desktop.hide_app", {}),
        ("Can you minimize the current app?", "desktop.minimize_window", {}),
        ("Could you minimize the foreground application please?", "desktop.minimize_window", {}),
        ("Can you hide Chrome?", "app.hide", {"app_name": "Google Chrome"}),
        ("Could you minimize Chrome please?", "app.minimize", {"app_name": "Google Chrome"}),
        ("Can you close the current window?", "desktop.close_window", {}),
        ("Could you quit Slack please?", "app.quit", {"app_name": "Slack"}),
    )

    for prompt, tool_name, tool_input in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == tool_name


def test_daily_desktop_entrypoint_routes_screen_and_visible_ui_language_to_desktop_tools() -> None:
    cases = (
        (
            "帮我截个屏",
            "screen.capture",
            {"reason": "user asked to capture the screen"},
        ),
        (
            "你能看看现在有哪些按钮吗",
            "desktop.ui_elements",
            {"role_filter": "button", "limit": 80},
        ),
        (
            "Can you list the visible buttons?",
            "desktop.ui_elements",
            {"role_filter": "button", "limit": 80},
        ),
        (
            "Can you inspect the current UI?",
            "desktop.ui_elements",
            {"role_filter": "", "limit": 80},
        ),
        (
            "读取当前窗口内容",
            "desktop.ui_elements",
            {"role_filter": "text", "limit": 80},
        ),
        (
            "read the current window",
            "desktop.ui_elements",
            {"role_filter": "text", "limit": 80},
        ),
        (
            "点击可见的登录按钮",
            "desktop.click_ui_element",
            {"target": "登录", "role_filter": "button", "limit": 80, "click_count": 1},
        ),
        (
            "点一下登录",
            "desktop.click_ui_element",
            {"target": "登录", "role_filter": "button", "limit": 80, "click_count": 1},
        ),
        (
            "点击确认",
            "desktop.click_ui_element",
            {"target": "确认", "role_filter": "button", "limit": 80, "click_count": 1},
        ),
        (
            "Can you click the login button?",
            "desktop.click_ui_element",
            {"target": "login", "role_filter": "button", "limit": 80, "click_count": 1},
        ),
        (
            "click login",
            "desktop.click_ui_element",
            {"target": "login", "role_filter": "button", "limit": 80, "click_count": 1},
        ),
        (
            "Can you type hello into the search field?",
            "desktop.type_into_ui_element",
            {"target": "search", "text": "hello", "role_filter": "text", "limit": 80},
        ),
    )

    for prompt, tool_name, tool_input in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == tool_name


def test_daily_desktop_entrypoint_routes_browser_search_and_current_page_find() -> None:
    search_requests = daily_desktop_entrypoint_requests("Can you search Chrome for weather?")

    assert search_requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=weather"},
        }
    ]

    find_requests = daily_desktop_entrypoint_requests("search current page for hello")

    assert find_requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
    ]
    assert daily_desktop_user_metadata(find_requests) == {
        "daily_desktop_intent": True,
        "daily_desktop_source": "daily_desktop_intent",
        "daily_desktop_planning_reason": "clear_daily_desktop_intent",
        "daily_desktop_tool": "desktop.safe_shortcut",
        "daily_desktop_tools": ["desktop.safe_shortcut", "desktop.safe_type_text"],
    }


def test_daily_desktop_entrypoint_routes_polite_safe_shortcut_and_key_questions_to_desktop_tools() -> None:
    cases = (
        ("你可以帮我复制一下吗", "desktop.safe_shortcut", {"action": "copy"}),
        ("你能帮我粘贴吗", "desktop.safe_shortcut", {"action": "paste"}),
        ("你能帮我全选吗", "desktop.safe_shortcut", {"action": "select_all"}),
        ("你可以帮我撤销吗", "desktop.safe_shortcut", {"action": "undo"}),
        ("你能帮我按一下Escape吗", "desktop.safe_key", {"action": "escape", "repeat_count": 1}),
        ("你可以帮我按Tab吗", "desktop.safe_key", {"action": "tab", "repeat_count": 1}),
        ("Can you copy?", "desktop.safe_shortcut", {"action": "copy"}),
        ("Could you paste?", "desktop.safe_shortcut", {"action": "paste"}),
        ("Would you select all please?", "desktop.safe_shortcut", {"action": "select_all"}),
        ("Could you press Escape?", "desktop.safe_key", {"action": "escape", "repeat_count": 1}),
        ("Can you hit Tab?", "desktop.safe_key", {"action": "tab", "repeat_count": 1}),
    )

    for prompt, tool_name, tool_input in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == tool_name

    approval_cases = (
        ("按 Command+L", "desktop.hotkey", {"key": "l", "modifiers": ["command"]}),
        ("你能帮我按Command L吗", "desktop.hotkey", {"key": "l", "modifiers": ["command"]}),
        ("Can you press Command L?", "desktop.hotkey", {"key": "l", "modifiers": ["command"]}),
        (
            "Could you open Chrome and press Command L?",
            "app.open_and_hotkey",
            {"app_name": "Google Chrome", "key": "l", "modifiers": ["command"]},
        ),
    )

    for prompt, tool_name, tool_input in approval_cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == tool_name


def test_daily_desktop_entrypoint_routes_music_app_playback_questions_to_desktop_tools() -> None:
    cases = (
        ("打开网易云并播放", "media.music_app_open_and_play", {"app_name": "网易云音乐"}),
        ("可以帮我打开网易云并播放吗", "media.music_app_open_and_play", {"app_name": "网易云音乐"}),
        ("Could you launch Spotify and play music?", "media.music_app_open_and_play", {"app_name": "Spotify"}),
        ("能帮我播放 Apple Music 吗", "media.apple_music_open_and_play", {}),
    )

    for prompt, tool_name, tool_input in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests) == {
            "daily_desktop_intent": True,
            "daily_desktop_source": "daily_desktop_intent",
            "daily_desktop_planning_reason": "clear_daily_desktop_intent",
            "daily_desktop_tool": tool_name,
            "daily_desktop_tools": [tool_name],
        }


def test_daily_desktop_entrypoint_routes_colloquial_music_queries_to_apple_music() -> None:
    cases = (
        ("放点周杰伦", {"query": "周杰伦"}),
        ("播点轻音乐", {"query": "轻音乐"}),
        ("来点轻音乐", {"query": "轻音乐"}),
        ("play some jazz", {"query": "jazz"}),
        ("play some Taylor Swift", {"query": "Taylor Swift"}),
        ("play Some Nights", {"query": "Some Nights"}),
        ("search Apple Music for Taylor Swift and play it", {"query": "Taylor Swift"}),
    )

    for prompt, tool_input in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "media.apple_music_play",
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == "media.apple_music_play"

    assert daily_desktop_entrypoint_requests("播点音乐") == [
        {
            "protocol": "json_fallback",
            "tool": "media.apple_music_open_and_play",
            "input": {},
        }
    ]


def test_daily_desktop_entrypoint_routes_colloquial_volume_questions_to_desktop_tools() -> None:
    cases = (
        ("大点声", {"action": "up"}),
        ("大一点声", {"action": "up"}),
        ("调到35音量", {"action": "set", "level": 35}),
        ("volume 35", {"action": "set", "level": 35}),
        ("set sound to 35", {"action": "set", "level": 35}),
        ("sound up", {"action": "up"}),
        ("sound down", {"action": "down"}),
    )

    for prompt, tool_input in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "system.volume",
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == "system.volume"

    assert daily_desktop_entrypoint_requests("亮一点") == []
    assert daily_desktop_entrypoint_requests("暗一点") == []


def test_daily_desktop_structured_recovery_metadata_projects_exact_low_risk_request() -> None:
    metadata = {
        "desktop_permission_recovery": True,
        "recovery_tool": "system.settings_open",
        "recovery_input": {"target": "屏幕录制权限"},
        "recovery_permission_target": "screen_recording",
        "recovery_risk_level": "low",
    }

    direct_request = daily_desktop_direct_metadata_request(
        metadata,
        allowed_tools=["system.settings_open"],
    )
    requests = daily_desktop_entrypoint_requests(
        "修复屏幕录制",
        metadata=metadata,
        allowed_tools=["system.settings_open"],
    )

    assert requests == [direct_request]
    assert requests[0] == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "屏幕录制权限"},
        "source": "daily_desktop_metadata",
        "planning_reason": "structured_recovery_metadata",
    }
    assert daily_desktop_user_metadata(requests) == {
        "daily_desktop_intent": True,
        "daily_desktop_source": "daily_desktop_metadata",
        "daily_desktop_planning_reason": "structured_recovery_metadata",
        "daily_desktop_tool": "system.settings_open",
        "daily_desktop_tools": ["system.settings_open"],
    }
    assert daily_desktop_planned_timeline(
        "修复屏幕录制",
        metadata=metadata,
        allowed_tools=["system.settings_open"],
    ) == [
        {
            "event": "agent.desktop.intent_planned",
            "detail": "system.settings_open",
            "tool": "system.settings_open",
            "status": "planned",
            "source": "daily_desktop_metadata",
            "planning_reason": "structured_recovery_metadata",
            "input_preview": {"target": "屏幕录制权限"},
        }
    ]
    assert "屏幕录制权限" in daily_desktop_recovery_execution_prompt("修复屏幕录制", metadata)
