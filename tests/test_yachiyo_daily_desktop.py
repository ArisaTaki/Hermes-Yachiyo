"""Shared daily desktop runtime helper tests."""

from __future__ import annotations

from datetime import date, timedelta

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


def test_daily_desktop_entrypoint_routes_permission_diagnosis_questions() -> None:
    for prompt in (
        "为什么不能打开应用？",
        "为什么不能读取屏幕？",
        "为什么不能查看屏幕？",
    ):
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "desktop.permissions",
                "input": {},
            }
        ]
        assert daily_desktop_user_metadata(requests) == {
            "daily_desktop_intent": True,
            "daily_desktop_source": "daily_desktop_intent",
            "daily_desktop_planning_reason": "clear_daily_desktop_intent",
            "daily_desktop_tool": "desktop.permissions",
            "daily_desktop_tools": ["desktop.permissions"],
        }


def test_daily_desktop_entrypoint_routes_polite_app_open_questions_to_desktop_tool() -> None:
    cases = (
        ("你能帮我打开微信吗", "WeChat"),
        ("能否帮我打开微信", "WeChat"),
        ("能否帮我启动备忘录", "Notes"),
        ("把微信开了", "WeChat"),
        ("你能启动一下备忘录吗", "Notes"),
        ("打开短信", "Messages"),
        ("把 Finder 拉起来", "Finder"),
        ("把日历启动起来", "Calendar"),
        ("把备忘录开起来", "Notes"),
        ("启动Chrome起来", "Google Chrome"),
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


def test_daily_desktop_entrypoint_routes_finder_quick_look_to_app_safe_shortcut() -> None:
    cases = (
        ("打开Finder然后按空格", "app.open_and_safe_shortcut"),
        ("Finder按空格", "app.focus_and_safe_shortcut"),
        ("Finder快速查看选中项", "app.focus_and_safe_shortcut"),
    )

    for prompt, tool_name in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": {"app_name": "Finder", "action": "finder_quick_look"},
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == tool_name


def test_daily_desktop_entrypoint_routes_finder_new_folder_to_app_safe_shortcut() -> None:
    cases = (
        ("打开访达新建文件夹", "app.open_and_safe_shortcut"),
        ("打开 Finder 新建文件夹", "app.open_and_safe_shortcut"),
        ("Finder 新建文件夹", "app.focus_and_safe_shortcut"),
        ("Finder 创建目录", "app.focus_and_safe_shortcut"),
        ("Finder make a new folder", "app.focus_and_safe_shortcut"),
    )

    for prompt, tool_name in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": {"app_name": "Finder", "action": "new_folder"},
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == tool_name

    assert daily_desktop_entrypoint_requests("Chrome 新建文件夹") == []
    assert daily_desktop_entrypoint_requests("新建文件夹") == []


def test_daily_desktop_entrypoint_routes_finder_item_safe_shortcuts() -> None:
    cases = (
        ("打开 Finder 重命名选中文件", "app.open_and_safe_shortcut", "rename_selected"),
        ("Finder 重命名选中文件", "app.focus_and_safe_shortcut", "rename_selected"),
        ("Finder rename selected file", "app.focus_and_safe_shortcut", "rename_selected"),
        ("打开 Finder 上一级文件夹", "app.open_and_safe_shortcut", "parent_folder"),
        ("Finder 上一级目录", "app.focus_and_safe_shortcut", "parent_folder"),
        ("Finder 回到上级目录", "app.focus_and_safe_shortcut", "parent_folder"),
        ("Finder open parent folder", "app.focus_and_safe_shortcut", "parent_folder"),
        ("在 Finder 里显示简介", "app.focus_and_safe_shortcut", "finder_get_info"),
        ("Finder 显示简介", "app.focus_and_safe_shortcut", "finder_get_info"),
        ("Finder get info", "app.focus_and_safe_shortcut", "finder_get_info"),
        ("打开 Finder 复制选中文件", "app.open_and_safe_shortcut", "copy"),
        ("Finder 复制选中文件", "app.focus_and_safe_shortcut", "copy"),
        ("Finder copy selected file", "app.focus_and_safe_shortcut", "copy"),
    )

    for prompt, tool_name, action in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": {"app_name": "Finder", "action": action},
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == tool_name

    assert daily_desktop_entrypoint_requests("重命名当前选中的文件") == []
    assert daily_desktop_entrypoint_requests("Finder 删除选中文件") == []
    assert daily_desktop_entrypoint_requests("Finder 把选中文件移到废纸篓") == []


def test_daily_desktop_entrypoint_routes_app_blank_new_item_shortcuts() -> None:
    cases = (
        ("打开备忘录新建", "app.open_and_safe_shortcut", "Notes", "new_note"),
        ("备忘录新建", "app.focus_and_safe_shortcut", "Notes", "new_note"),
        ("打开提醒事项新建", "app.open_and_safe_shortcut", "Reminders", "new_reminder"),
        ("提醒事项新建", "app.focus_and_safe_shortcut", "Reminders", "new_reminder"),
        ("打开日历新建", "app.open_and_safe_shortcut", "Calendar", "new_event"),
        ("日历新建", "app.focus_and_safe_shortcut", "Calendar", "new_event"),
        ("打开 Slack 新建消息", "app.open_and_safe_shortcut", "Slack", "new_message"),
        ("Slack 新建消息", "app.focus_and_safe_shortcut", "Slack", "new_message"),
        ("Slack new message", "app.focus_and_safe_shortcut", "Slack", "new_message"),
        ("微信新建聊天", "app.focus_and_safe_shortcut", "WeChat", "new_message"),
        ("Messages compose message", "app.focus_and_safe_shortcut", "Messages", "new_message"),
    )

    for prompt, tool_name, app_name, action in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": {"app_name": app_name, "action": action},
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == tool_name

    assert daily_desktop_entrypoint_requests("打开提醒事项新建提醒") == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Reminders", "action": "new_reminder"},
        }
    ]
    assert daily_desktop_entrypoint_requests("Word 新建消息") == []


def test_daily_desktop_entrypoint_routes_browser_app_utility_shortcuts() -> None:
    cases = (
        ("打开 Chrome 新建无痕窗口", "app.open_and_safe_shortcut", "new_private_window"),
        ("Chrome 新建无痕窗口", "app.focus_and_safe_shortcut", "new_private_window"),
        ("Chrome open incognito window", "app.focus_and_safe_shortcut", "new_private_window"),
        ("打开 Chrome 开发者工具", "app.open_and_safe_shortcut", "open_devtools"),
        ("Chrome 打开历史记录", "app.focus_and_safe_shortcut", "show_history"),
        ("Chrome 聚焦地址栏", "app.focus_and_safe_shortcut", "focus_address_bar"),
    )

    for prompt, tool_name, action in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": {"app_name": "Google Chrome", "action": action},
            }
        ]

    internal_page_cases = (
        ("Chrome 打开下载内容", "app.focus_and_safe_shortcut", "chrome://downloads/"),
        ("Chrome 打开书签", "app.focus_and_safe_shortcut", "chrome://bookmarks/"),
        ("Chrome 打开扩展程序", "app.focus_and_safe_shortcut", "chrome://extensions/"),
        ("打开 Chrome 下载内容", "app.open_and_safe_shortcut", "chrome://downloads/"),
        ("open Chrome extensions", "app.open_and_safe_shortcut", "chrome://extensions/"),
    )
    for prompt, tool_name, internal_url in internal_page_cases:
        assert daily_desktop_entrypoint_requests(prompt) == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_type_text",
                "input": {"text": internal_url},
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.search_submit",
                "input": {},
            },
        ]


def test_daily_desktop_entrypoint_routes_app_command_palette_and_preferences() -> None:
    cases = (
        ("打开 VS Code 命令面板", "app.open_and_safe_shortcut", "Visual Studio Code", "command_palette"),
        ("在 VS Code 里打开命令面板", "app.focus_and_safe_shortcut", "Visual Studio Code", "command_palette"),
        ("VS Code command palette", "app.focus_and_safe_shortcut", "Visual Studio Code", "command_palette"),
        ("打开 Obsidian 命令面板", "app.open_and_safe_shortcut", "Obsidian", "obsidian_command_palette"),
        ("在 Obsidian 里打开命令面板", "app.focus_and_safe_shortcut", "Obsidian", "obsidian_command_palette"),
        ("Obsidian command palette", "app.focus_and_safe_shortcut", "Obsidian", "obsidian_command_palette"),
        ("打开 Slack 偏好设置", "app.open_and_safe_shortcut", "Slack", "preferences"),
        ("在 Slack 里打开偏好设置", "app.focus_and_safe_shortcut", "Slack", "preferences"),
        ("Slack preferences", "app.focus_and_safe_shortcut", "Slack", "preferences"),
        ("打开 Chrome 设置", "app.open_and_safe_shortcut", "Google Chrome", "preferences"),
        ("在 Chrome 里打开设置", "app.focus_and_safe_shortcut", "Google Chrome", "preferences"),
        ("Chrome settings", "app.focus_and_safe_shortcut", "Google Chrome", "preferences"),
    )

    for prompt, tool_name, app_name, action in cases:
        assert daily_desktop_entrypoint_requests(prompt) == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": {"app_name": app_name, "action": action},
            }
        ]

    assert daily_desktop_entrypoint_requests("打开设置") == [
        {
            "protocol": "json_fallback",
            "tool": "system.settings_open",
            "input": {"target": "系统设置"},
        }
    ]
    assert (
        daily_desktop_entrypoint_requests(
            "在 Slack 里打开偏好设置",
            allowed_tools=("system.settings_open",),
        )
        == []
    )


def test_daily_desktop_entrypoint_routes_command_palette_input_and_execution() -> None:
    assert daily_desktop_entrypoint_requests("在 VS Code 里打开命令面板输入 Format Document") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
    ]
    assert daily_desktop_entrypoint_requests("打开 VS Code 命令面板并输入 Format Document") == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
    ]
    assert daily_desktop_entrypoint_requests("在 VS Code 里打开命令面板输入 Format Document 并回车") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_entrypoint_requests(
        "在 VS Code 里打开命令面板输入 Format Document 然后选择第一个结果"
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_entrypoint_requests(
        "在 VS Code 里打开命令面板输入 Format Document 后按下箭头再确认"
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_key",
            "input": {"action": "arrow_down", "repeat_count": 1},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_entrypoint_requests(
        "VS Code command palette type Format Document then select first result"
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Obsidian command palette type Toggle reading view and press enter") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Obsidian", "action": "obsidian_command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Toggle reading view"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert (
        daily_desktop_entrypoint_requests(
            "在 VS Code 里执行命令 Format Document",
            allowed_tools=("app.focus_and_safe_shortcut", "desktop.safe_type_text"),
        )
        == []
    )


def test_daily_desktop_entrypoint_routes_app_fullscreen_to_app_safe_shortcut() -> None:
    cases = (
        ("Chrome 最大化", "app.focus_and_safe_shortcut", "Google Chrome"),
        ("Chrome 全屏", "app.focus_and_safe_shortcut", "Google Chrome"),
        ("打开 Chrome 并最大化", "app.open_and_safe_shortcut", "Google Chrome"),
        ("open Chrome and fullscreen", "app.open_and_safe_shortcut", "Google Chrome"),
        ("切到 Slack 并全屏", "app.focus_and_safe_shortcut", "Slack"),
        ("focus Slack and maximize", "app.focus_and_safe_shortcut", "Slack"),
    )

    for prompt, tool_name, app_name in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": {"app_name": app_name, "action": "toggle_full_screen"},
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == tool_name


def test_daily_desktop_entrypoint_routes_app_status_questions_to_desktop_tool() -> None:
    cases = (
        ("Chrome 开着吗", "Google Chrome"),
        ("Google Chrome 在运行吗", "Google Chrome"),
        ("检查一下 Slack 是否运行", "Slack"),
        ("看看 Slack 开没开", "Slack"),
        ("Finder 是否运行", "Finder"),
    )

    for prompt, app_name in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "app.status",
                "input": {"app_name": app_name},
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == "app.status"


def test_daily_desktop_entrypoint_routes_polite_focus_and_show_questions_to_desktop_tools() -> None:
    cases = (
        ("你能帮我切到Chrome吗", "app.focus", {"app_name": "Google Chrome"}),
        ("能否帮我切到微信", "app.focus", {"app_name": "WeChat"}),
        ("能否帮我把微信切到前台", "app.focus", {"app_name": "WeChat"}),
        ("你可以帮我聚焦Chrome吗", "app.focus", {"app_name": "Google Chrome"}),
        ("你能帮我显示Finder吗", "app.show", {"app_name": "Finder"}),
        ("能否帮我显示微信", "app.show", {"app_name": "WeChat"}),
        ("你能帮我还原微信吗", "app.show", {"app_name": "WeChat"}),
        ("bring calculator up", "app.focus", {"app_name": "Calculator"}),
        ("打开微信到前台", "app.show", {"app_name": "WeChat"}),
        ("把Chrome叫出来", "app.show", {"app_name": "Google Chrome"}),
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

    app_window_sequence = daily_desktop_entrypoint_requests("打开微信然后隐藏")

    assert app_window_sequence == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.hide",
            "input": {"app_name": "WeChat"},
        },
    ]
    assert daily_desktop_user_metadata(app_window_sequence)["daily_desktop_tools"] == [
        "app.open",
        "app.hide",
    ]

    focus_window_sequence = daily_desktop_entrypoint_requests("切到微信然后隐藏")

    assert focus_window_sequence == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.hide",
            "input": {"app_name": "WeChat"},
        },
    ]
    assert daily_desktop_user_metadata(focus_window_sequence)["daily_desktop_tools"] == [
        "app.focus",
        "app.hide",
    ]

    minimize_window_sequence = daily_desktop_entrypoint_requests("打开 Chrome 然后最小化")

    assert minimize_window_sequence == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.minimize",
            "input": {"app_name": "Google Chrome"},
        },
    ]


def test_daily_desktop_entrypoint_routes_current_app_window_control_to_desktop_tools() -> None:
    cases = (
        ("你可以帮我隐藏一下前台应用吗", "desktop.hide_app", {}),
        ("把这个应用隐藏起来", "desktop.hide_app", {}),
        ("把当前 app 藏起来", "desktop.hide_app", {}),
        ("Can you hide the current app?", "desktop.hide_app", {}),
        ("Could you hide the foreground app please?", "desktop.hide_app", {}),
        ("你能帮我收起一下当前应用吗", "desktop.hide_app", {}),
        ("显示隐藏的应用", "desktop.show_all_apps", {}),
        ("显示所有隐藏应用", "desktop.show_all_apps", {}),
        ("show all hidden apps", "desktop.show_all_apps", {}),
        ("隐藏当前窗口", "desktop.minimize_window", {}),
        ("隐藏前台窗口", "desktop.minimize_window", {}),
        ("把窗口收起来", "desktop.minimize_window", {}),
        ("Can you minimize the current app?", "desktop.minimize_window", {}),
        ("Could you minimize the foreground application please?", "desktop.minimize_window", {}),
        ("Can you hide Chrome?", "app.hide", {"app_name": "Google Chrome"}),
        ("把Chrome藏起来", "app.hide", {"app_name": "Google Chrome"}),
        ("Could you minimize Chrome please?", "app.minimize", {"app_name": "Google Chrome"}),
        ("关闭一下当前窗口", "desktop.close_window", {}),
        ("Can you close the current window?", "desktop.close_window", {}),
        ("退出当前应用", "desktop.quit_app", {}),
        ("关掉这个应用", "desktop.quit_app", {}),
        ("close the current app", "desktop.quit_app", {}),
        ("quit the foreground application", "desktop.quit_app", {}),
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

    app_scoped_close_window = daily_desktop_entrypoint_requests("微信关闭窗口")
    assert app_scoped_close_window == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.close_window",
            "input": {},
        },
    ]
    assert daily_desktop_user_metadata(app_scoped_close_window)["daily_desktop_tools"] == [
        "app.focus",
        "desktop.close_window",
    ]

    assert daily_desktop_entrypoint_requests("当前窗口是什么") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
        }
    ]
    assert daily_desktop_entrypoint_requests("现在前台是什么") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
        }
    ]
    assert daily_desktop_entrypoint_requests("我正在用什么应用") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
        }
    ]
    for prompt in (
        "现在前台是不是 Chrome",
        "前台是不是 Chrome",
        "当前前台是不是 Google Chrome",
        "现在是不是在 Chrome 里",
        "我现在是不是在微信",
        "is Chrome frontmost",
        "is Chrome the active app",
        "is the active app Chrome",
        "which app is frontmost",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == [
            {
                "protocol": "json_fallback",
                "tool": "desktop.active_window",
                "input": {},
            }
        ]

    assert daily_desktop_entrypoint_requests("我现在是不是在家") == []


def test_daily_desktop_entrypoint_routes_system_window_hotkeys_and_system_apps() -> None:
    cases = (
        (
            "当前窗口最大化",
            "desktop.safe_shortcut",
            {"action": "toggle_full_screen"},
        ),
        (
            "退出全屏",
            "desktop.safe_shortcut",
            {"action": "toggle_full_screen"},
        ),
        (
            "maximize the current window",
            "desktop.safe_shortcut",
            {"action": "toggle_full_screen"},
        ),
        (
            "leave full screen",
            "desktop.safe_shortcut",
            {"action": "toggle_full_screen"},
        ),
        (
            "切换到上一个应用",
            "desktop.safe_shortcut",
            {"action": "switch_previous_app"},
        ),
        (
            "switch to previous app",
            "desktop.safe_shortcut",
            {"action": "switch_previous_app"},
        ),
        (
            "切到下一个应用",
            "desktop.safe_shortcut",
            {"action": "switch_next_app"},
        ),
        (
            "switch to next app",
            "desktop.safe_shortcut",
            {"action": "switch_next_app"},
        ),
        ("打开启动台", "app.open", {"app_name": "Launchpad"}),
        ("open launchpad", "app.open", {"app_name": "Launchpad"}),
        ("打开控制中心", "app.open", {"app_name": "Control Center"}),
        ("open control center", "app.open", {"app_name": "Control Center"}),
        ("打开通知中心", "app.open", {"app_name": "Notification Center"}),
        ("open notification center", "app.open", {"app_name": "Notification Center"}),
        ("打开声音设置", "system.settings_open", {"target": "声音"}),
        ("open sound settings", "system.settings_open", {"target": "声音"}),
        ("打开键盘设置", "system.settings_open", {"target": "键盘"}),
        ("open keyboard settings", "system.settings_open", {"target": "键盘"}),
        ("打开通知设置", "system.settings_open", {"target": "通知"}),
        ("open notification settings", "system.settings_open", {"target": "通知"}),
        ("打开电池设置", "system.settings_open", {"target": "电池"}),
        ("open battery settings", "system.settings_open", {"target": "电池"}),
        ("打开鼠标设置", "system.settings_open", {"target": "鼠标"}),
        ("open mouse settings", "system.settings_open", {"target": "鼠标"}),
        ("打开触控板设置", "system.settings_open", {"target": "触控板"}),
        ("open trackpad settings", "system.settings_open", {"target": "触控板"}),
        ("打开打印机设置", "system.settings_open", {"target": "打印机与扫描仪"}),
        ("open printers settings", "system.settings_open", {"target": "打印机与扫描仪"}),
        ("打开专注模式设置", "system.settings_open", {"target": "专注模式"}),
        ("打开墙纸设置", "system.settings_open", {"target": "墙纸"}),
        ("open wallpaper settings", "system.settings_open", {"target": "墙纸"}),
        ("打开桌面与程序坞设置", "system.settings_open", {"target": "桌面与程序坞"}),
        ("open desktop and dock settings", "system.settings_open", {"target": "桌面与程序坞"}),
        ("打开屏幕保护程序设置", "system.settings_open", {"target": "屏幕保护程序"}),
        ("打开 Siri 设置", "system.settings_open", {"target": "Siri"}),
        ("打开语言与地区设置", "system.settings_open", {"target": "语言与地区"}),
        ("打开日期与时间设置", "system.settings_open", {"target": "日期与时间"}),
        ("打开软件更新", "system.settings_open", {"target": "软件更新"}),
        ("open software update", "system.settings_open", {"target": "软件更新"}),
        ("打开储存空间设置", "system.settings_open", {"target": "储存空间"}),
        ("open storage settings", "system.settings_open", {"target": "储存空间"}),
        ("打开登录项设置", "system.settings_open", {"target": "登录项"}),
        ("打开用户与群组设置", "system.settings_open", {"target": "用户与群组"}),
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

    assert daily_desktop_entrypoint_requests("把当前窗口放左边") == []
    assert daily_desktop_entrypoint_requests("tile current window left") == []
    assert daily_desktop_entrypoint_requests("当前窗口是什么") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
        }
    ]


def test_daily_desktop_entrypoint_routes_running_apps_language() -> None:
    for prompt in ("现在开了哪些应用", "列一下打开的应用"):
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "desktop.running_apps",
                "input": {},
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == "desktop.running_apps"


def test_daily_desktop_entrypoint_routes_window_list_language() -> None:
    assert daily_desktop_entrypoint_requests("显示当前窗口列表") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.windows",
            "input": {},
        }
    ]
    assert daily_desktop_entrypoint_requests("显示微信窗口列表") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.windows",
            "input": {"app_name": "WeChat"},
        }
    ]
    assert daily_desktop_entrypoint_requests("列出Chrome窗口") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.windows",
            "input": {"app_name": "Google Chrome"},
        }
    ]


def test_daily_desktop_entrypoint_routes_screen_and_visible_ui_language_to_desktop_tools() -> None:
    cases = (
        (
            "帮我截个屏",
            "screen.capture",
            {"reason": "user asked to capture the screen"},
        ),
        (
            "截一下图",
            "screen.capture",
            {"reason": "user asked to capture the screen"},
        ),
        (
            "截取选区",
            "desktop.safe_shortcut",
            {"action": "screenshot_selection"},
        ),
        (
            "capture selected area",
            "desktop.safe_shortcut",
            {"action": "screenshot_selection"},
        ),
        (
            "打开截图工具",
            "desktop.safe_shortcut",
            {"action": "screenshot_toolbar"},
        ),
        (
            "打开截图面板",
            "desktop.safe_shortcut",
            {"action": "screenshot_toolbar"},
        ),
        (
            "open screenshot toolbar",
            "desktop.safe_shortcut",
            {"action": "screenshot_toolbar"},
        ),
        (
            "打开录屏工具",
            "desktop.safe_shortcut",
            {"action": "screenshot_toolbar"},
        ),
        (
            "screen recording toolbar",
            "desktop.safe_shortcut",
            {"action": "screenshot_toolbar"},
        ),
        (
            "你能看看现在有哪些按钮吗",
            "desktop.ui_elements",
            {"role_filter": "button", "limit": 80},
        ),
        (
            "当前页面有哪些按钮",
            "desktop.ui_elements",
            {"role_filter": "button", "limit": 80},
        ),
        (
            "登录按钮在哪",
            "desktop.ui_elements",
            {"role_filter": "button", "limit": 80},
        ),
        (
            "能看到哪些按钮",
            "desktop.ui_elements",
            {"role_filter": "button", "limit": 80},
        ),
        (
            "where is the login button",
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
            "当前界面点击登录",
            "desktop.click_ui_element",
            {"target": "登录", "role_filter": "button", "limit": 80, "click_count": 1},
        ),
        (
            "前台点登录",
            "desktop.click_ui_element",
            {"target": "登录", "role_filter": "button", "limit": 80, "click_count": 1},
        ),
        (
            "在当前界面点击登录按钮",
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
        (
            "打开微信搜索框输入文件传输助手",
            "app.open_and_type_into_ui_element",
            {
                "app_name": "WeChat",
                "target": "搜索",
                "text": "文件传输助手",
                "role_filter": "text",
                "limit": 80,
            },
        ),
        (
            "微信在搜索框输入文件传输助手",
            "app.focus_and_type_into_ui_element",
            {
                "app_name": "WeChat",
                "target": "搜索",
                "text": "文件传输助手",
                "role_filter": "text",
                "limit": 80,
            },
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
    selected_search_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
    ]
    for prompt in (
        "搜索选中的内容",
        "搜索当前选中文字",
        "用浏览器搜索选中的内容",
        "用 Google 搜索选中的内容",
        "google selected text",
        "search selected text",
        "search the current selection",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == selected_search_requests
    assert daily_desktop_user_metadata(selected_search_requests)["daily_desktop_tools"] == [
        "desktop.safe_shortcut",
        "app.open_and_safe_shortcut",
        "desktop.safe_shortcut",
        "desktop.search_submit",
    ]
    assert daily_desktop_entrypoint_requests("用 Safari 搜索选中的内容") == [
        selected_search_requests[0],
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Safari", "action": "focus_address_bar"},
        },
        selected_search_requests[2],
        selected_search_requests[3],
    ]
    assert daily_desktop_entrypoint_requests(
        "search selected text",
        allowed_tools=("browser.open_url",),
    ) == []

    clipboard_search_requests = [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
    ]
    for prompt in (
        "把剪贴板内容拿去搜索",
        "搜索剪贴板内容",
        "用浏览器搜索剪贴板内容",
        "用 Google 搜索剪贴板内容",
        "search the clipboard",
        "search clipboard contents",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == clipboard_search_requests
    assert daily_desktop_entrypoint_requests(
        "搜索剪贴板内容",
        allowed_tools=("browser.open_url", "clipboard.read"),
    ) == []
    assert daily_desktop_entrypoint_requests("google clipboard") == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=clipboard"},
        }
    ]
    assert daily_desktop_entrypoint_requests("search WeChat for file transfer") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "file transfer"},
        },
    ]
    assert daily_desktop_entrypoint_requests("find file transfer in WeChat") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "file transfer"},
        },
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
    selected_find_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "在当前页面查找选中的内容",
        "在当前网页查找当前选中文字",
        "用选中内容查找当前页面",
        "find selected text on current page",
        "find current selection in page",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == selected_find_requests
    assert daily_desktop_user_metadata(selected_find_requests)["daily_desktop_tools"] == [
        "desktop.safe_shortcut",
        "desktop.safe_shortcut",
        "desktop.safe_shortcut",
    ]
    clipboard_find_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "在当前页面查找剪贴板内容",
        "用剪贴板内容查找当前网页",
        "find clipboard contents on current page",
        "find the clipboard in current page",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == clipboard_find_requests
    assert (
        daily_desktop_entrypoint_requests(
            "在当前页面查找剪贴板内容",
            allowed_tools=("desktop.safe_type_text",),
        )
        == []
    )
    assert daily_desktop_entrypoint_requests("在微信里查找选中的内容") == [
        selected_find_requests[0],
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        selected_find_requests[2],
    ]
    assert daily_desktop_entrypoint_requests("在 Slack 里查找剪贴板内容") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        clipboard_find_requests[1],
    ]

    assert daily_desktop_entrypoint_requests("打开第一个搜索结果") == [
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        }
    ]
    assert daily_desktop_entrypoint_requests("在当前输入框输入 hello") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        }
    ]
    assert daily_desktop_entrypoint_requests("在当前输入框输入文本 hello") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        }
    ]
    assert daily_desktop_entrypoint_requests("输入文本 hello") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        }
    ]
    assert daily_desktop_entrypoint_requests("type hello in current input") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        }
    ]
    send_requests = daily_desktop_entrypoint_requests("微信输入 hello 并发送")

    assert send_requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_type_text",
            "input": {"app_name": "WeChat", "text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_user_metadata(send_requests)["daily_desktop_tools"] == [
        "app.focus_and_safe_type_text",
        "desktop.submit_foreground",
    ]
    open_send_requests = daily_desktop_entrypoint_requests("打开微信发送 hello")

    assert open_send_requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_type_text",
            "input": {"app_name": "WeChat", "text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_user_metadata(open_send_requests)["daily_desktop_tools"] == [
        "app.open_and_safe_type_text",
        "desktop.submit_foreground",
    ]
    assert daily_desktop_entrypoint_requests("打开搜索框输入 yachiyo 回车") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.type_into_ui_element",
            "input": {"target": "搜索", "text": "yachiyo", "role_filter": "text", "limit": 80},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
        },
    ]
    assert daily_desktop_entrypoint_requests("提交当前搜索") == [
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}}
    ]
    assert daily_desktop_entrypoint_requests("press enter to search") == [
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}}
    ]

    foreground_submit_requests = daily_desktop_entrypoint_requests("当前输入框发送")

    assert foreground_submit_requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        }
    ]
    assert daily_desktop_user_metadata(foreground_submit_requests)["daily_desktop_tools"] == [
        "desktop.submit_foreground"
    ]
    assert daily_desktop_entrypoint_requests("前台提交") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "submit"},
        }
    ]
    paste_send_requests = daily_desktop_entrypoint_requests("当前输入框粘贴并发送")

    assert paste_send_requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_user_metadata(paste_send_requests)["daily_desktop_tools"] == [
        "desktop.safe_shortcut",
        "desktop.submit_foreground",
    ]
    selected_paste_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把选中的内容粘贴到当前输入框",
        "把当前选中文字粘贴到这里",
        "copy selected text and paste here",
        "paste selected text into current input",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == selected_paste_requests
    assert daily_desktop_user_metadata(selected_paste_requests)["daily_desktop_tools"] == [
        "desktop.safe_shortcut",
        "desktop.safe_shortcut",
    ]
    assert daily_desktop_entrypoint_requests("把选中文本粘贴并发送") == [
        *selected_paste_requests,
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert (
        daily_desktop_entrypoint_requests(
            "把选中的内容粘贴到当前输入框",
            allowed_tools=("desktop.submit_foreground",),
        )
        == []
    )
    for prompt, app_name in (
        ("把选中的内容粘贴到 Slack", "Slack"),
        ("把选中的内容粘贴到 Slack 当前输入框", "Slack"),
        ("把选中的内容粘贴到微信", "WeChat"),
        ("copy selection into Slack", "Slack"),
        ("paste selected text in Slack", "Slack"),
    ):
        assert daily_desktop_entrypoint_requests(prompt) == [
            selected_paste_requests[0],
            {
                "protocol": "json_fallback",
                "tool": "app.focus_and_safe_shortcut",
                "input": {"app_name": app_name, "action": "paste"},
            },
        ]
    for prompt in ("打开 Slack 粘贴选中内容", "open Slack paste selected text"):
        assert daily_desktop_entrypoint_requests(prompt) == [
            selected_paste_requests[0],
            {
                "protocol": "json_fallback",
                "tool": "app.open_and_safe_shortcut",
                "input": {"app_name": "Slack", "action": "paste"},
            },
        ]
    current_page_link_paste_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
        selected_paste_requests[1],
    ]
    for prompt in (
        "把当前网页链接粘贴到当前输入框",
        "paste current page link here",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == current_page_link_paste_requests
    assert daily_desktop_entrypoint_requests("把当前网页链接粘贴到 Slack") == [
        current_page_link_paste_requests[0],
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "paste"},
        },
    ]
    assert daily_desktop_entrypoint_requests("在 Slack 粘贴当前网页链接") == [
        current_page_link_paste_requests[0],
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "paste"},
        },
    ]
    assert daily_desktop_entrypoint_requests("把剪贴板内容粘贴到 Slack") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "paste"},
        },
    ]
    current_content_copy_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "select_all"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    for prompt in (
        "复制当前网页内容",
        "把当前页面内容复制到剪贴板",
        "copy current page text",
        "copy current window content",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == current_content_copy_requests
    assert (
        daily_desktop_entrypoint_requests(
            "复制当前网页内容",
            allowed_tools=("browser.current_page",),
        )
        == []
    )
    assert daily_desktop_entrypoint_requests("复制当前网页链接") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
    ]
    for prompt in (
        "把当前窗口内容粘贴到 Slack",
        "把当前页面内容粘贴到 Slack",
        "paste current page content into Slack",
        "在 Slack 粘贴当前页面内容",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == [
            *current_content_copy_requests,
            {
                "protocol": "json_fallback",
                "tool": "app.focus_and_safe_shortcut",
                "input": {"app_name": "Slack", "action": "paste"},
            },
        ]
    assert daily_desktop_entrypoint_requests("打开 Slack 粘贴当前页面内容") == [
        *current_content_copy_requests,
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "paste"},
        },
    ]
    for prompt in (
        "把当前页面内容粘贴到当前输入框",
        "paste current page content here",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == []
    current_content_comm_requests = [
        *current_content_copy_requests,
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    for prompt in (
        "把当前窗口内容发给微信文件传输助手",
        "把当前页面内容发给微信文件传输助手",
        "微信给文件传输助手发送当前页面内容",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == current_content_comm_requests
    assert (
        daily_desktop_entrypoint_requests(
            "把当前页面内容发给微信文件传输助手",
            allowed_tools=("desktop.ui_elements",),
        )
        == []
    )

    app_submit_requests = daily_desktop_entrypoint_requests("微信按回车发送")

    assert app_submit_requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_user_metadata(app_submit_requests) == {
        "daily_desktop_intent": True,
        "daily_desktop_source": "daily_desktop_intent",
        "daily_desktop_planning_reason": "clear_daily_desktop_intent",
        "daily_desktop_tool": "app.focus",
        "daily_desktop_tools": ["app.focus", "desktop.submit_foreground"],
    }
    assert daily_desktop_entrypoint_requests("在 Slack 里发送") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Slack"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_entrypoint_requests("在微信里确认发送") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]

    app_hotkey_requests = daily_desktop_entrypoint_requests("微信按回车")

    assert app_hotkey_requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_hotkey",
            "input": {"app_name": "WeChat", "key": "return", "modifiers": []},
        }
    ]
    assert daily_desktop_user_metadata(app_hotkey_requests)["daily_desktop_tool"] == "app.focus_and_hotkey"

    comm_requests = daily_desktop_entrypoint_requests("微信找张三并发送你好")

    assert comm_requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "张三"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "你好"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_user_metadata(comm_requests)["daily_desktop_tools"] == [
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_type_text",
        "desktop.submit_foreground",
    ]

    comm_paste_requests = daily_desktop_entrypoint_requests("微信给文件传输助手粘贴并发送")

    assert comm_paste_requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_user_metadata(comm_paste_requests)["daily_desktop_tools"] == [
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_shortcut",
        "desktop.submit_foreground",
    ]

    comm_clipboard_requests = daily_desktop_entrypoint_requests("把剪贴板内容发给微信文件传输助手")

    assert comm_clipboard_requests == comm_paste_requests
    assert daily_desktop_user_metadata(comm_clipboard_requests)["daily_desktop_tools"] == [
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_shortcut",
        "desktop.submit_foreground",
    ]

    comm_selected_requests = daily_desktop_entrypoint_requests("微信给文件传输助手发送选中的内容")

    assert comm_selected_requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_user_metadata(comm_selected_requests)["daily_desktop_tools"] == [
        "desktop.safe_shortcut",
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_shortcut",
        "desktop.submit_foreground",
    ]
    assert (
        daily_desktop_entrypoint_requests("把当前选中文本发给微信文件传输助手")
        == comm_selected_requests
    )
    assert (
        daily_desktop_entrypoint_requests("复制当前选中内容发给微信文件传输助手")
        == comm_selected_requests
    )
    assert daily_desktop_entrypoint_requests("把当前选中文件发给微信文件传输助手") == []

    comm_link_requests = daily_desktop_entrypoint_requests("把当前网页链接发给微信文件传输助手")

    assert comm_link_requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_user_metadata(comm_link_requests)["daily_desktop_tools"] == [
        "desktop.safe_shortcut",
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_shortcut",
        "desktop.submit_foreground",
    ]

    assert daily_desktop_entrypoint_requests("复制当前网页链接发给微信文件传输助手") == comm_link_requests
    assert daily_desktop_entrypoint_requests("复制当前网页链接并发给微信文件传输助手") == comm_link_requests

    open_comm_requests = daily_desktop_entrypoint_requests("打开微信发消息给张三你好")

    assert open_comm_requests[0] == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "WeChat", "action": "find"},
    }
    assert open_comm_requests[1]["input"] == {"text": "张三"}
    assert open_comm_requests[3]["input"] == {"text": "你好"}
    assert daily_desktop_user_metadata(open_comm_requests)["daily_desktop_tools"] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_type_text",
        "desktop.submit_foreground",
    ]

    copy_link_requests = daily_desktop_entrypoint_requests("复制当前网页链接")

    assert copy_link_requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
    ]
    assert daily_desktop_entrypoint_requests("copy current page link") == copy_link_requests
    assert daily_desktop_entrypoint_requests("把当前网址放到剪贴板") == copy_link_requests
    assert daily_desktop_entrypoint_requests("当前页地址复制一下") == copy_link_requests
    assert daily_desktop_entrypoint_requests("把当前链接复制给我") == copy_link_requests
    assert daily_desktop_user_metadata(copy_link_requests) == {
        "daily_desktop_intent": True,
        "daily_desktop_source": "daily_desktop_intent",
        "daily_desktop_planning_reason": "clear_daily_desktop_intent",
        "daily_desktop_tool": "desktop.safe_shortcut",
        "daily_desktop_tools": ["desktop.safe_shortcut"],
    }

    assert daily_desktop_entrypoint_requests("当前网页是什么") == [
        {
            "protocol": "json_fallback",
            "tool": "browser.current_page",
            "input": {},
        }
    ]
    for prompt in (
        "读取当前网页链接",
        "当前网页链接是什么",
        "当前网址是什么",
        "what is current page url?",
        "read current page link",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == [
            {
                "protocol": "json_fallback",
                "tool": "browser.current_page",
                "input": {},
            }
        ]
    for prompt in ("read current webpage", "extract current page text"):
        assert daily_desktop_entrypoint_requests(prompt) == [
            {
                "protocol": "json_fallback",
                "tool": "browser.extract_text",
                "input": {},
            }
        ]
    assert daily_desktop_entrypoint_requests("focus Chrome and extract page text") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.extract_text",
            "input": {},
        },
    ]


def test_daily_desktop_entrypoint_routes_dynamic_sources_to_ui_inputs() -> None:
    selected_copy = {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "copy"},
    }
    current_page_link_copy = {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "copy_current_page_link"},
    }
    current_content_copy = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "select_all"},
        },
        selected_copy,
    ]
    foreground_search_click = {
        "protocol": "json_fallback",
        "tool": "desktop.click_ui_element",
        "input": {"target": "搜索", "role_filter": "text", "limit": 80, "click_count": 1},
    }
    foreground_address_click = {
        "protocol": "json_fallback",
        "tool": "desktop.click_ui_element",
        "input": {"target": "地址", "role_filter": "text", "limit": 80, "click_count": 1},
    }
    paste = {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "paste"},
    }
    assert daily_desktop_entrypoint_requests("把选中的内容输入到搜索框") == [
        selected_copy,
        foreground_search_click,
        paste,
    ]
    assert daily_desktop_entrypoint_requests("把选中的内容填到当前输入框") == [
        selected_copy,
        paste,
    ]
    assert daily_desktop_entrypoint_requests("把剪贴板内容输入到搜索框") == [
        foreground_search_click,
        paste,
    ]
    assert daily_desktop_entrypoint_requests("把剪贴板内容填到当前输入框") == [paste]
    assert daily_desktop_entrypoint_requests("把当前网页链接输入到地址栏") == [
        current_page_link_copy,
        foreground_address_click,
        paste,
    ]
    assert daily_desktop_entrypoint_requests("把当前页面内容输入到搜索框") == [
        *current_content_copy,
        foreground_search_click,
        paste,
    ]
    assert daily_desktop_entrypoint_requests("把当前页面内容输入到当前输入框") == []
    assert (
        daily_desktop_entrypoint_requests(
            "把选中的内容输入到搜索框",
            allowed_tools=("desktop.safe_type_text",),
        )
        == []
    )

    slack_search_click = {
        "protocol": "json_fallback",
        "tool": "app.focus_and_click_ui_element",
        "input": {
            "app_name": "Slack",
            "target": "搜索",
            "role_filter": "text",
            "limit": 80,
            "click_count": 1,
        },
    }
    for prompt in (
        "把选中的内容输入到 Slack 搜索框",
        "Slack 搜索框输入选中的内容",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == [
            selected_copy,
            slack_search_click,
            paste,
        ]
    assert daily_desktop_entrypoint_requests("把剪贴板内容输入到 Slack 搜索框") == [
        slack_search_click,
        paste,
    ]
    assert daily_desktop_entrypoint_requests("把当前网页链接输入到 Slack 搜索框") == [
        current_page_link_copy,
        slack_search_click,
        paste,
    ]
    assert daily_desktop_entrypoint_requests("把当前页面内容输入到 Slack 搜索框") == [
        *current_content_copy,
        slack_search_click,
        paste,
    ]
    assert daily_desktop_entrypoint_requests("打开 Slack 搜索框输入选中的内容") == [
        selected_copy,
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "搜索",
                "role_filter": "text",
                "limit": 80,
                "click_count": 1,
            },
        },
        paste,
    ]


def test_daily_desktop_entrypoint_routes_app_scoped_ui_input_suffixes() -> None:
    assert daily_desktop_entrypoint_requests("在 Slack 的消息框输入 hello") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_type_into_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "消息",
                "text": "hello",
                "role_filter": "text",
                "limit": 80,
            },
        }
    ]
    assert daily_desktop_entrypoint_requests("在微信里的搜索框输入文件传输助手") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_type_into_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "搜索",
                "text": "文件传输助手",
                "role_filter": "text",
                "limit": 80,
            },
        }
    ]
    assert daily_desktop_entrypoint_requests("在 Linear 上的搜索框输入 ticket 并回车") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_type_into_ui_element",
            "input": {
                "app_name": "Linear",
                "target": "搜索",
                "text": "ticket",
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
    assert (
        daily_desktop_entrypoint_requests(
            "在 Slack 的消息框输入 hello",
            allowed_tools=("app.focus_and_safe_shortcut", "desktop.safe_type_text"),
        )
        == []
    )


def test_daily_desktop_entrypoint_routes_dynamic_source_browser_open() -> None:
    selected_open_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
    ]
    for prompt in (
        "打开选中的链接",
        "打开当前选中的网址",
        "用浏览器打开选中的链接",
        "open selected link",
        "open selected URL",
        "open the current selection in browser",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == selected_open_requests
    assert daily_desktop_user_metadata(selected_open_requests)["daily_desktop_tools"] == [
        "desktop.safe_shortcut",
        "app.open_and_safe_shortcut",
        "desktop.safe_shortcut",
        "desktop.search_submit",
    ]
    assert daily_desktop_entrypoint_requests("用 Safari 打开选中的链接") == [
        selected_open_requests[0],
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Safari", "action": "focus_address_bar"},
        },
        selected_open_requests[2],
        selected_open_requests[3],
    ]
    assert daily_desktop_entrypoint_requests("open selected link in Safari") == [
        selected_open_requests[0],
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Safari", "action": "focus_address_bar"},
        },
        selected_open_requests[2],
        selected_open_requests[3],
    ]
    assert daily_desktop_entrypoint_requests(
        "open selected URL",
        allowed_tools=("browser.open_url", "app.open"),
    ) == []

    clipboard_open_requests = [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
    ]
    for prompt in (
        "打开剪贴板里的链接",
        "打开剪贴板内容里的网址",
        "用浏览器打开剪贴板内容",
        "open clipboard link",
        "open the clipboard URL",
        "open clipboard contents",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == clipboard_open_requests
    assert daily_desktop_entrypoint_requests(
        "打开剪贴板里的链接",
        allowed_tools=("clipboard.read", "browser.open_url"),
    ) == []
    assert daily_desktop_entrypoint_requests("打开当前网页链接") == [
        {
            "protocol": "json_fallback",
            "tool": "browser.current_page",
            "input": {},
        }
    ]


def test_daily_desktop_entrypoint_routes_direct_browser_and_finder_targets() -> None:
    cases = (
        (
            "refresh the current page",
            "desktop.safe_shortcut",
            {"action": "refresh"},
        ),
        (
            "刷新当前页面",
            "desktop.safe_shortcut",
            {"action": "refresh"},
        ),
        (
            "open a new tab",
            "desktop.safe_shortcut",
            {"action": "new_tab"},
        ),
        (
            "新开一个标签页",
            "desktop.safe_shortcut",
            {"action": "new_tab"},
        ),
        (
            "打开 GitHub 首页",
            "browser.open_url",
            {"url": "https://github.com"},
        ),
        (
            "上 GitHub",
            "browser.open_url",
            {"url": "https://github.com"},
        ),
        (
            "打开 B 站首页",
            "browser.open_url",
            {"url": "https://www.bilibili.com"},
        ),
        (
            "上 B 站",
            "browser.open_url",
            {"url": "https://www.bilibili.com"},
        ),
        (
            "打开推特首页",
            "browser.open_url",
            {"url": "https://x.com"},
        ),
        (
            "打开贴吧",
            "browser.open_url",
            {"url": "https://tieba.baidu.com"},
        ),
        (
            "打开下载目录里的最新文件",
            "desktop.open_path",
            {"path": "latest_download"},
        ),
        (
            "打开最后下载的文件",
            "desktop.open_path",
            {"path": "latest_download"},
        ),
        (
            "打开上一个下载的文件",
            "desktop.open_path",
            {"path": "latest_download"},
        ),
        (
            "打开当前选中的 Finder 文件",
            "desktop.open_path",
            {"path": "finder_selection"},
        ),
        (
            "显示当前选中的 Finder 文件",
            "desktop.reveal_path",
            {"path": "finder_selection"},
        ),
        (
            "显示当前选中文件",
            "desktop.reveal_path",
            {"path": "finder_selection"},
        ),
        (
            "打开桌面文件夹",
            "desktop.open_path",
            {"path": "~/Desktop"},
        ),
        (
            "把下载文件夹拉起来",
            "desktop.open_path",
            {"path": "~/Downloads"},
        ),
        (
            "拉起下载文件夹",
            "desktop.open_path",
            {"path": "~/Downloads"},
        ),
        (
            "打开访达里的下载文件夹",
            "desktop.open_path",
            {"path": "~/Downloads"},
        ),
        (
            "打开下载目录给我看",
            "desktop.open_path",
            {"path": "~/Downloads"},
        ),
        (
            "打开下载列表",
            "desktop.open_path",
            {"path": "~/Downloads"},
        ),
        (
            "打开下载记录",
            "desktop.open_path",
            {"path": "~/Downloads"},
        ),
        (
            "打开下载页面",
            "desktop.open_path",
            {"path": "~/Downloads"},
        ),
        (
            "打开下载文件夹并排序",
            "desktop.open_path",
            {"path": "~/Downloads"},
        ),
        (
            "open downloads page",
            "desktop.open_path",
            {"path": "~/Downloads"},
        ),
        (
            "打开用户目录",
            "desktop.open_path",
            {"path": "~"},
        ),
        (
            "打开个人主目录",
            "desktop.open_path",
            {"path": "~"},
        ),
        (
            "打开家目录",
            "desktop.open_path",
            {"path": "~"},
        ),
        (
            "open user directory",
            "desktop.open_path",
            {"path": "~"},
        ),
        (
            "打开我的文稿",
            "desktop.open_path",
            {"path": "~/Documents"},
        ),
        (
            "打开 iCloud Drive",
            "desktop.open_path",
            {"path": "~/Library/Mobile Documents/com~apple~CloudDocs"},
        ),
        (
            "打开 iCloud 云盘",
            "desktop.open_path",
            {"path": "~/Library/Mobile Documents/com~apple~CloudDocs"},
        ),
        (
            "打开共享文件夹",
            "desktop.open_path",
            {"path": "/Users/Shared"},
        ),
        (
            "在 Finder 中显示 iCloud 云盘",
            "desktop.reveal_path",
            {"path": "~/Library/Mobile Documents/com~apple~CloudDocs"},
        ),
        (
            "在 Finder 中显示共享文件夹",
            "desktop.reveal_path",
            {"path": "/Users/Shared"},
        ),
        (
            "把下载文件夹在 Finder 里显示出来",
            "desktop.reveal_path",
            {"path": "~/Downloads"},
        ),
        (
            "show Downloads folder in Finder",
            "desktop.reveal_path",
            {"path": "~/Downloads"},
        ),
        (
            "打开当前工作区",
            "desktop.open_path",
            {"path": "."},
        ),
        (
            "打开当前项目",
            "desktop.open_path",
            {"path": "."},
        ),
        (
            "打开当前仓库",
            "desktop.open_path",
            {"path": "."},
        ),
        (
            "打开项目目录",
            "desktop.open_path",
            {"path": "."},
        ),
        (
            "在 Finder 中显示当前工作区",
            "desktop.reveal_path",
            {"path": "."},
        ),
        (
            "在 Finder 中显示当前项目",
            "desktop.reveal_path",
            {"path": "."},
        ),
        (
            "在 Finder 中显示项目目录",
            "desktop.reveal_path",
            {"path": "."},
        ),
        (
            "打开垃圾桶",
            "desktop.open_path",
            {"path": "~/.Trash"},
        ),
        (
            "打开回收站",
            "desktop.open_path",
            {"path": "~/.Trash"},
        ),
        (
            "打开临时目录",
            "desktop.open_path",
            {"path": "/tmp"},
        ),
        (
            "打开根目录",
            "desktop.open_path",
            {"path": "/"},
        ),
        (
            "open trash folder",
            "desktop.open_path",
            {"path": "~/.Trash"},
        ),
        (
            "click the first search result",
            "browser.click",
            {"selector": "search-result=1", "click_count": 1},
        ),
        (
            "点击当前页面第一个搜索结果",
            "browser.click",
            {"selector": "search-result=1", "click_count": 1},
        ),
        (
            "type hello in current webpage search field",
            "browser.type_text",
            {
                "selector": (
                    'input[type="search"], input[name="q"], textarea[name="q"], '
                    'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
                    'input[aria-label*="search" i], input[placeholder*="search" i]'
                ),
                "text": "hello",
            },
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

    assert daily_desktop_entrypoint_requests("清空垃圾桶") == []
    assert daily_desktop_entrypoint_requests("打开项目") == []


def test_daily_desktop_entrypoint_routes_finder_find_language() -> None:
    assert daily_desktop_entrypoint_requests("打开 Finder 找下载文件") == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "下载文件"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Finder 找下载文件") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "下载文件"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Finder look for Downloads") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Downloads"},
        },
    ]
    finder_open_first_requests = daily_desktop_entrypoint_requests(
        "打开 Finder 查找 Downloads 然后打开第一个"
    )

    assert finder_open_first_requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Downloads"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.click_ui_element",
            "input": {"target": "第一个结果", "role_filter": "", "limit": 80, "click_count": 2},
        },
    ]
    assert daily_desktop_user_metadata(finder_open_first_requests)["daily_desktop_tools"] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.click_ui_element",
    ]

    assert daily_desktop_entrypoint_requests("在 Finder 搜索 report 并打开第一个结果") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "report"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.click_ui_element",
            "input": {"target": "第一个结果", "role_filter": "", "limit": 80, "click_count": 2},
        },
    ]
    assert daily_desktop_entrypoint_requests("在 Slack 搜索 Alice 并选择第一个结果") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.click_ui_element",
            "input": {"target": "第一个结果", "role_filter": "", "limit": 80, "click_count": 1},
        },
    ]
    assert daily_desktop_entrypoint_requests("Slack search Alice then choose first result") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.click_ui_element",
            "input": {"target": "first result", "role_filter": "", "limit": 80, "click_count": 1},
        },
    ]
    assert daily_desktop_entrypoint_requests("在 Slack 搜索 Alice 后按下箭头再确认") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_key",
            "input": {"action": "arrow_down", "repeat_count": 1},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Slack search Alice then press down arrow and enter") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_key",
            "input": {"action": "arrow_down", "repeat_count": 1},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_entrypoint_requests("微信打开搜索") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        }
    ]


def test_daily_desktop_entrypoint_routes_app_prefix_click_language() -> None:
    assert daily_desktop_entrypoint_requests("Chrome 点登录") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "text=登录", "click_count": 1},
        },
    ]
    assert daily_desktop_entrypoint_requests("Slack 点搜索") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "搜索",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
    ]
    assert daily_desktop_entrypoint_requests("微信点搜索") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "搜索",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
    ]
    assert daily_desktop_entrypoint_requests("微信点击搜索框") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "搜索",
                "role_filter": "text",
                "limit": 80,
                "click_count": 1,
            },
        },
    ]
    assert daily_desktop_entrypoint_requests("在微信里的通讯录按钮点一下") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "通讯录",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
    ]
    assert daily_desktop_entrypoint_requests("在 Slack 的搜索按钮点一下") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "搜索",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
    ]
    assert daily_desktop_entrypoint_requests("在 Linear 上的创建按钮点击") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Linear",
                "target": "创建",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
    ]
    assert daily_desktop_entrypoint_requests("在微信里的通讯录按钮双击") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "通讯录",
                "role_filter": "button",
                "limit": 80,
                "click_count": 2,
            },
        },
    ]
    assert (
        daily_desktop_entrypoint_requests(
            "在 Slack 的搜索按钮点一下",
            allowed_tools=("desktop.safe_type_text",),
        )
        == []
    )


def test_daily_desktop_entrypoint_routes_click_then_submit_sequences() -> None:
    assert daily_desktop_entrypoint_requests("Slack 点击确认按钮然后确认") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "确认",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_entrypoint_requests("打开 Linear 点击创建按钮然后确认") == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_click_ui_element",
            "input": {
                "app_name": "Linear",
                "target": "创建",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Slack click Confirm button then confirm") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "Confirm",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Linear click Create button then press enter") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Linear",
                "target": "Create",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Slack click Send button then send") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "Send",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]


def test_daily_desktop_entrypoint_routes_click_type_submit_sequences() -> None:
    assert daily_desktop_entrypoint_requests("Slack 点击消息框输入 hello 并发送") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "消息",
                "role_filter": "text",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_entrypoint_requests("打开 Slack 点击消息框输入 hello 并发送") == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "消息",
                "role_filter": "text",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Slack click message field and type hello then send") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "message",
                "role_filter": "text",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Slack 点击搜索框输入 Alice 并回车") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
    ]
    assert daily_desktop_entrypoint_requests("Slack 点击搜索按钮然后输入 Alice") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "搜索",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Slack click Search button then type Alice") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "Search",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
    ]
    assert daily_desktop_entrypoint_requests("在 Linear 里点击创建按钮然后输入 Task title") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Linear",
                "target": "创建",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Task title"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Slack 点击搜索按钮然后输入 Alice 并回车") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "搜索",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]


def test_daily_desktop_entrypoint_routes_app_scoped_safe_keys_and_scroll() -> None:
    assert daily_desktop_entrypoint_requests("在 Slack 里按 Tab") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_key",
            "input": {"app_name": "Slack", "action": "tab", "repeat_count": 1},
        }
    ]
    assert daily_desktop_entrypoint_requests("在 Slack 里按两次 Tab") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_key",
            "input": {"app_name": "Slack", "action": "tab", "repeat_count": 2},
        }
    ]
    assert daily_desktop_entrypoint_requests("在 Slack 里按 Command F") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        }
    ]
    assert daily_desktop_entrypoint_requests("在 Slack 里向下滚动两页") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_scroll",
            "input": {"app_name": "Slack", "direction": "down", "pages": 2},
        }
    ]
    assert daily_desktop_entrypoint_requests("切到 Slack 后取消") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_key",
            "input": {"app_name": "Slack", "action": "escape", "repeat_count": 1},
        }
    ]
    assert daily_desktop_entrypoint_requests("打开 Slack 后取消") == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_key",
            "input": {"app_name": "Slack", "action": "escape", "repeat_count": 1},
        }
    ]
    assert daily_desktop_entrypoint_requests("打开 Finder 然后按下方向键") == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_key",
            "input": {"app_name": "Finder", "action": "arrow_down", "repeat_count": 1},
        }
    ]
    assert daily_desktop_entrypoint_requests("在 Finder 里按上方向键") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_key",
            "input": {"app_name": "Finder", "action": "arrow_up", "repeat_count": 1},
        }
    ]
    assert daily_desktop_entrypoint_requests("在 Slack 里按回车") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_hotkey",
            "input": {"app_name": "Slack", "key": "return", "modifiers": []},
        }
    ]
    assert daily_desktop_entrypoint_requests("打开 Slack 后按回车") == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_hotkey",
            "input": {"app_name": "Slack", "key": "return", "modifiers": []},
        }
    ]
    assert daily_desktop_entrypoint_requests("在 Slack 里按确认按钮") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "确认",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        }
    ]
    assert (
        daily_desktop_entrypoint_requests(
            "在 Slack 里按 Tab",
            allowed_tools=("app.focus_and_click_ui_element",),
        )
        == []
    )
    assert (
        daily_desktop_entrypoint_requests(
            "在 Slack 里按回车",
            allowed_tools=("app.focus_and_click_ui_element",),
        )
        == []
    )


def test_daily_desktop_entrypoint_routes_app_browser_search_language() -> None:
    assert daily_desktop_entrypoint_requests("打开推特") == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://x.com"},
        }
    ]
    assert daily_desktop_entrypoint_requests("Chrome 搜索 OpenAI") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=OpenAI"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Chrome 点击搜索框输入 yachiyo") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
    ]
    assert daily_desktop_entrypoint_requests("打开 Chrome 点击搜索栏输入 yachiyo 并搜索") == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
    ]
    assert daily_desktop_entrypoint_requests("打开 Chrome 新建标签页然后搜索 OpenAI") == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "new_tab"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=OpenAI"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Chrome 后退再刷新") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "browser_back"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "refresh"},
        },
    ]
    assert daily_desktop_entrypoint_requests("把Chrome启动起来刷新一下") == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "refresh"},
        },
    ]
    assert daily_desktop_entrypoint_requests("启动Chrome起来刷新一下") == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "refresh"},
        },
    ]
    assert daily_desktop_entrypoint_requests("Chrome 搜索 OpenAI 并打开第一个结果") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=OpenAI"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]
    assert daily_desktop_entrypoint_requests("在 Chrome 里搜索 OpenAI 并打开第一个结果") == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=OpenAI"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]
    assert daily_desktop_entrypoint_requests("打开 YouTube 搜索 lo fi 并播放") == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.youtube.com/results?search_query=lo+fi"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]
    assert daily_desktop_entrypoint_requests("YouTube 搜索 lo fi") == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.youtube.com/results?search_query=lo+fi"},
        },
    ]
    assert daily_desktop_entrypoint_requests("在 B站 搜索 周杰伦 并播放") == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://search.bilibili.com/all?keyword=%E5%91%A8%E6%9D%B0%E4%BC%A6"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]


def test_daily_desktop_entrypoint_routes_clipboard_requests() -> None:
    assert daily_desktop_entrypoint_requests("设置剪贴板为 hello") == [
        {
            "protocol": "json_fallback",
            "tool": "clipboard.write",
            "input": {"text": "hello"},
        }
    ]
    assert daily_desktop_entrypoint_requests("set clipboard to hello") == [
        {
            "protocol": "json_fallback",
            "tool": "clipboard.write",
            "input": {"text": "hello"},
        }
    ]
    assert daily_desktop_entrypoint_requests("把 hello 复制一下") == [
        {
            "protocol": "json_fallback",
            "tool": "clipboard.write",
            "input": {"text": "hello"},
        }
    ]
    assert daily_desktop_entrypoint_requests(
        "把 hello 复制一下",
        allowed_tools=("app.focus_and_safe_shortcut",),
    ) == []
    clipboard_note_requests = [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Notes", "action": "new_note"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把剪贴板内容写进备忘录",
        "把剪贴板内容记到备忘录",
        "把剪贴板内容放到备忘录",
        "把剪贴板内容加到笔记",
        "把剪贴板内容新建成备忘录",
        "用剪贴板内容新建备忘录",
        "paste clipboard into a new note",
        "create a note from clipboard",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == clipboard_note_requests
        assert daily_desktop_user_metadata(clipboard_note_requests)["daily_desktop_tools"] == [
            "app.open_and_safe_shortcut",
            "desktop.safe_shortcut",
        ]
    assert daily_desktop_entrypoint_requests(
        "把剪贴板内容写进备忘录",
        allowed_tools=("clipboard.read", "notes.create"),
    ) == []
    assert daily_desktop_entrypoint_requests("复制选中文字并读取剪贴板") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
        },
    ]
    assert daily_desktop_entrypoint_requests("copy selected text and read clipboard") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
        },
    ]
    assert daily_desktop_entrypoint_requests("复制选中文本") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        }
    ]


def test_daily_desktop_entrypoint_routes_context_sources_to_notes() -> None:
    selected_text_note_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Notes", "action": "new_note"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把选中的内容写进备忘录",
        "把当前选中文字保存到备忘录",
        "把选中的文字新建成备忘录",
        "把选中的内容加入备忘录",
        "save selected text to a new note",
        "create a note from selected text",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == selected_text_note_requests
    assert daily_desktop_user_metadata(selected_text_note_requests)["daily_desktop_tools"] == [
        "desktop.safe_shortcut",
        "app.open_and_safe_shortcut",
        "desktop.safe_shortcut",
    ]
    assert daily_desktop_entrypoint_requests(
        "create a note from selected text",
        allowed_tools=("notes.create",),
    ) == []

    current_page_link_note_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Notes", "action": "new_note"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把当前网页链接写进备忘录",
        "把当前网页链接保存到备忘录",
        "把当前网页存到备忘录",
        "把当前网页加入备忘录",
        "save current page link to a note",
        "create a note from current page link",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == current_page_link_note_requests
    assert daily_desktop_entrypoint_requests(
        "create a note from current page link",
        allowed_tools=("notes.create", "browser.current_page"),
    ) == []
    current_content_note_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "select_all"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Notes", "action": "new_note"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把当前网页内容写进备忘录",
        "把当前页面内容保存到备忘录",
        "把当前网页正文新建成备忘录",
        "把当前网页文字放到笔记",
        "把当前页面复制到备忘录",
        "复制当前页面内容到备忘录",
        "把当前窗口内容写进备忘录",
        "把当前应用内容保存到备忘录",
        "save current page content to a new note",
        "create a note from current page content",
        "copy current page to a note",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == current_content_note_requests
    assert daily_desktop_entrypoint_requests(
        "create a note from current page content",
        allowed_tools=("notes.create", "browser.current_page"),
    ) == []
    assert daily_desktop_entrypoint_requests("把当前屏幕内容写进备忘录") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "text", "limit": 80},
        }
    ]


def test_daily_desktop_entrypoint_routes_dynamic_sources_to_reminders() -> None:
    selected_reminder_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Reminders", "action": "new_reminder"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把选中的内容创建成提醒事项",
        "把当前选中文字加入提醒事项",
        "用选中内容新建提醒",
        "create a reminder from selected text",
        "add selected text to reminders",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == selected_reminder_requests
    assert daily_desktop_user_metadata(selected_reminder_requests)["daily_desktop_tools"] == [
        "desktop.safe_shortcut",
        "app.open_and_safe_shortcut",
        "desktop.safe_shortcut",
    ]
    assert daily_desktop_entrypoint_requests(
        "create a reminder from selected text",
        allowed_tools=("reminders.create",),
    ) == []

    clipboard_reminder_requests = [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Reminders", "action": "new_reminder"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把剪贴板内容创建成提醒事项",
        "把剪贴板内容加入提醒事项",
        "用剪贴板内容新建提醒",
        "create a reminder from clipboard",
        "create a reminder from the clipboard",
        "add clipboard contents to reminders",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == clipboard_reminder_requests
    assert daily_desktop_entrypoint_requests(
        "把剪贴板内容加入提醒事项",
        allowed_tools=("clipboard.read", "reminders.create"),
    ) == []
    current_page_link_reminder_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Reminders", "action": "new_reminder"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把当前网页链接创建成提醒事项",
        "把当前网页链接加入提醒事项",
        "用当前网页链接新建提醒",
        "create a reminder from current page link",
        "add current page link to reminders",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == current_page_link_reminder_requests
    assert daily_desktop_entrypoint_requests(
        "把当前网页链接加入提醒事项",
        allowed_tools=("browser.current_page", "reminders.create"),
    ) == []
    current_content_reminder_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "select_all"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Reminders", "action": "new_reminder"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把当前页面内容创建成提醒事项",
        "把当前窗口内容创建成提醒事项",
        "create a reminder from current page content",
        "add current window content to reminders",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == current_content_reminder_requests
    assert daily_desktop_entrypoint_requests(
        "把当前页面内容创建成提醒事项",
        allowed_tools=("desktop.ui_elements", "reminders.create"),
    ) == []
    assert daily_desktop_entrypoint_requests("新建提醒事项：买牛奶") == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "买牛奶"},
        }
    ]


def test_daily_desktop_entrypoint_routes_dynamic_sources_to_calendar() -> None:
    selected_calendar_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Calendar", "action": "new_event"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把选中的内容创建成日历事件",
        "把当前选中文字加入日历",
        "用选中内容新建日程",
        "create a calendar event from selected text",
        "add selected text to calendar",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == selected_calendar_requests
    assert daily_desktop_user_metadata(selected_calendar_requests)["daily_desktop_tools"] == [
        "desktop.safe_shortcut",
        "app.open_and_safe_shortcut",
        "desktop.safe_shortcut",
    ]
    assert daily_desktop_entrypoint_requests(
        "create a calendar event from selected text",
        allowed_tools=("calendar.create_event",),
    ) == []

    clipboard_calendar_requests = [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Calendar", "action": "new_event"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把剪贴板内容创建成日历事件",
        "把剪贴板内容加入日历",
        "用剪贴板内容新建日程",
        "create a calendar event from clipboard",
        "add clipboard contents to calendar",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == clipboard_calendar_requests
    assert daily_desktop_entrypoint_requests(
        "把剪贴板内容加入日历",
        allowed_tools=("clipboard.read", "calendar.create_event"),
    ) == []
    current_page_link_calendar_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Calendar", "action": "new_event"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把当前网页链接创建成日历事件",
        "把当前网页链接加入日历",
        "用当前网页链接新建日程",
        "create a calendar event from current page link",
        "add current page link to calendar",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == current_page_link_calendar_requests
    assert daily_desktop_entrypoint_requests(
        "把当前网页链接加入日历",
        allowed_tools=("browser.current_page", "calendar.create_event"),
    ) == []
    current_content_calendar_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "select_all"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Calendar", "action": "new_event"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把当前页面内容创建成日历事件",
        "把当前窗口内容加入日历",
        "create a calendar event from current page content",
        "add current window content to calendar",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == current_content_calendar_requests
    assert daily_desktop_entrypoint_requests(
        "把当前页面内容创建成日历事件",
        allowed_tools=("desktop.ui_elements", "calendar.create_event"),
    ) == []


def test_daily_desktop_entrypoint_routes_notes_and_time_first_reminders() -> None:
    today_2000 = f"{date.today().isoformat()}T20:00"
    tomorrow_0900 = f"{(date.today() + timedelta(days=1)).isoformat()}T09:00"
    tomorrow_1500 = f"{(date.today() + timedelta(days=1)).isoformat()}T15:00"
    tomorrow_1600 = f"{(date.today() + timedelta(days=1)).isoformat()}T16:00"
    after_tomorrow_0900 = f"{(date.today() + timedelta(days=2)).isoformat()}T09:00"

    assert daily_desktop_entrypoint_requests("帮我新建备忘录：明天买牛奶") == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "明天买牛奶"},
        }
    ]
    for prompt, body in (
        ("新建备忘录今天要买牛奶", "今天要买牛奶"),
        ("新建一个备忘录写 hello", "hello"),
        ("新建备忘录内容是 hello", "hello"),
        ("新建备忘录正文为 hello", "hello"),
        ("备忘录记一下今天要买牛奶", "今天要买牛奶"),
        ("在备忘录里新建 明天买牛奶", "明天买牛奶"),
        ("在备忘录里创建一条笔记 hello", "hello"),
        ("add a note buy milk", "buy milk"),
        ("make a note to buy milk", "buy milk"),
    ):
        assert daily_desktop_entrypoint_requests(prompt) == [
            {
                "protocol": "json_fallback",
                "tool": "notes.create",
                "input": {"body": body},
            }
        ]
    assert daily_desktop_entrypoint_requests("创建备忘录") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "new_note"},
        }
    ]
    for prompt, title, due_at in (
        ("提醒我明天买牛奶", "买牛奶", tomorrow_0900),
        ("新建提醒事项 明天买牛奶", "买牛奶", tomorrow_0900),
        ("创建提醒事项 后天买牛奶", "买牛奶", after_tomorrow_0900),
        ("提醒我今晚买牛奶", "买牛奶", today_2000),
    ):
        assert daily_desktop_entrypoint_requests(prompt) == [
            {
                "protocol": "json_fallback",
                "tool": "reminders.create",
                "input": {"title": title, "due_at": due_at},
            }
        ]
    assert daily_desktop_entrypoint_requests("明天上午九点提醒我开会") == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "开会", "due_at": tomorrow_0900},
        }
    ]
    for prompt, title in (
        ("帮我设个明天上午九点开会的提醒", "开会"),
        ("remind me tomorrow at 9 to join meeting", "join meeting"),
        ("set a reminder to buy milk tomorrow", "buy milk"),
    ):
        assert daily_desktop_entrypoint_requests(prompt) == [
            {
                "protocol": "json_fallback",
                "tool": "reminders.create",
                "input": {"title": title, "due_at": tomorrow_0900},
            }
        ]
    assert daily_desktop_entrypoint_requests("明天下午三点日历上加一个开会") == [
        {
            "protocol": "json_fallback",
            "tool": "calendar.create_event",
            "input": {
                "title": "开会",
                "start_at": tomorrow_1500,
                "end_at": tomorrow_1600,
            },
        }
    ]
    assert daily_desktop_entrypoint_requests("创建日历 明天下午三点开会") == [
        {
            "protocol": "json_fallback",
            "tool": "calendar.create_event",
            "input": {
                "title": "开会",
                "start_at": tomorrow_1500,
                "end_at": tomorrow_1600,
            },
        }
    ]
    assert daily_desktop_entrypoint_requests("创建日历 家庭") == []
    for prompt in (
        "schedule meeting tomorrow at 3pm",
        "add meeting tomorrow 3pm to calendar",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == [
            {
                "protocol": "json_fallback",
                "tool": "calendar.create_event",
                "input": {
                    "title": "meeting",
                    "start_at": tomorrow_1500,
                    "end_at": tomorrow_1600,
                },
            }
        ]
    assert daily_desktop_entrypoint_requests("add meeting tomorrow to calendar") == []


def test_daily_desktop_entrypoint_routes_colloquial_safe_scroll_language() -> None:
    cases = (
        ("向下滚动一点", {"direction": "down", "pages": 1}),
        ("当前窗口向下滚动一点", {"direction": "down", "pages": 1}),
        ("向上滚动一点", {"direction": "up", "pages": 1}),
        ("滚动到下面一点", {"direction": "down", "pages": 1}),
        ("滑到下方一点", {"direction": "down", "pages": 1}),
        ("滚动到上面一点", {"direction": "up", "pages": 1}),
        ("滑到上方一点", {"direction": "up", "pages": 1}),
    )

    for prompt, tool_input in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_scroll",
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == "desktop.safe_scroll"


def test_daily_desktop_entrypoint_routes_polite_safe_shortcut_and_key_questions_to_desktop_tools() -> None:
    cases = (
        ("你可以帮我复制一下吗", "desktop.safe_shortcut", {"action": "copy"}),
        ("你能帮我粘贴吗", "desktop.safe_shortcut", {"action": "paste"}),
        ("复制这个", "desktop.safe_shortcut", {"action": "copy"}),
        ("把这个复制一下", "desktop.safe_shortcut", {"action": "copy"}),
        ("你能帮我全选吗", "desktop.safe_shortcut", {"action": "select_all"}),
        ("你可以帮我撤销吗", "desktop.safe_shortcut", {"action": "undo"}),
        ("切到下一个窗口", "desktop.safe_shortcut", {"action": "next_window"}),
        ("切到上一个窗口", "desktop.safe_shortcut", {"action": "previous_window"}),
        ("打开任务控制中心", "desktop.safe_shortcut", {"action": "mission_control"}),
        ("显示当前应用窗口", "desktop.safe_shortcut", {"action": "application_windows"}),
        ("显示前台应用窗口", "desktop.safe_shortcut", {"action": "application_windows"}),
        ("应用窗口都显示一下", "desktop.safe_shortcut", {"action": "application_windows"}),
        ("显示当前应用的所有窗口", "desktop.safe_shortcut", {"action": "application_windows"}),
        ("打开聚焦搜索", "desktop.safe_shortcut", {"action": "spotlight_search"}),
        ("打开 Spotlight", "desktop.safe_shortcut", {"action": "spotlight_search"}),
        ("打开 emoji 面板", "desktop.safe_shortcut", {"action": "emoji_picker"}),
        ("锁屏", "desktop.safe_shortcut", {"action": "lock_screen"}),
        ("锁一下屏", "desktop.safe_shortcut", {"action": "lock_screen"}),
        ("打开强制退出窗口", "desktop.safe_shortcut", {"action": "force_quit_dialog"}),
        ("把这个网页关掉", "desktop.safe_shortcut", {"action": "close_tab"}),
        ("close this tab", "desktop.safe_shortcut", {"action": "close_tab"}),
        ("重新打开刚才关闭的标签页", "desktop.safe_shortcut", {"action": "reopen_closed_tab"}),
        ("刷新一下这个网页", "desktop.safe_shortcut", {"action": "refresh"}),
        ("聚焦地址栏", "desktop.safe_shortcut", {"action": "focus_address_bar"}),
        ("打开地址栏", "desktop.safe_shortcut", {"action": "focus_address_bar"}),
        ("新建标签", "desktop.safe_shortcut", {"action": "new_tab"}),
        ("新建无痕窗口", "desktop.safe_shortcut", {"action": "new_private_window"}),
        ("打开私密窗口", "desktop.safe_shortcut", {"action": "new_private_window"}),
        ("打开一个新窗口", "desktop.safe_shortcut", {"action": "new_window"}),
        ("新建浏览器窗口", "desktop.safe_shortcut", {"action": "new_window"}),
        ("创建备忘录", "desktop.safe_shortcut", {"action": "new_note"}),
        ("创建一个提醒", "desktop.safe_shortcut", {"action": "new_reminder"}),
        ("创建一个日程", "desktop.safe_shortcut", {"action": "new_event"}),
        ("前进下一页", "desktop.safe_shortcut", {"action": "browser_forward"}),
        ("把当前网页加入书签", "desktop.safe_shortcut", {"action": "bookmark_page"}),
        ("打开浏览器历史记录", "desktop.safe_shortcut", {"action": "show_history"}),
        ("打开开发者工具", "desktop.safe_shortcut", {"action": "open_devtools"}),
        ("网页放大", "desktop.safe_shortcut", {"action": "zoom_in"}),
        ("网页缩小", "desktop.safe_shortcut", {"action": "zoom_out"}),
        ("实际大小", "desktop.safe_shortcut", {"action": "reset_zoom"}),
        ("下一个标签", "desktop.safe_shortcut", {"action": "next_tab"}),
        ("上一个标签", "desktop.safe_shortcut", {"action": "previous_tab"}),
        ("你能帮我按一下Escape吗", "desktop.safe_key", {"action": "escape", "repeat_count": 1}),
        ("你可以帮我按Tab吗", "desktop.safe_key", {"action": "tab", "repeat_count": 1}),
        ("显示桌面", "desktop.safe_key", {"action": "show_desktop", "repeat_count": 1}),
        ("回到桌面", "desktop.safe_key", {"action": "show_desktop", "repeat_count": 1}),
        ("当前窗口按 Command V", "desktop.safe_shortcut", {"action": "paste"}),
        ("press command l", "desktop.safe_shortcut", {"action": "focus_address_bar"}),
        ("Can you copy?", "desktop.safe_shortcut", {"action": "copy"}),
        ("Could you paste?", "desktop.safe_shortcut", {"action": "paste"}),
        ("Would you select all please?", "desktop.safe_shortcut", {"action": "select_all"}),
        ("focus address bar", "desktop.safe_shortcut", {"action": "focus_address_bar"}),
        ("open incognito window", "desktop.safe_shortcut", {"action": "new_private_window"}),
        ("bookmark this page", "desktop.safe_shortcut", {"action": "bookmark_page"}),
        ("show browsing history", "desktop.safe_shortcut", {"action": "show_history"}),
        ("open devtools", "desktop.safe_shortcut", {"action": "open_devtools"}),
        ("zoom in page", "desktop.safe_shortcut", {"action": "zoom_in"}),
        ("zoom out page", "desktop.safe_shortcut", {"action": "zoom_out"}),
        ("reset zoom", "desktop.safe_shortcut", {"action": "reset_zoom"}),
        ("switch to next window", "desktop.safe_shortcut", {"action": "next_window"}),
        ("switch to previous window", "desktop.safe_shortcut", {"action": "previous_window"}),
        ("切换到上一个应用", "desktop.safe_shortcut", {"action": "switch_previous_app"}),
        ("switch to previous app", "desktop.safe_shortcut", {"action": "switch_previous_app"}),
        ("切到下一个应用", "desktop.safe_shortcut", {"action": "switch_next_app"}),
        ("switch to next app", "desktop.safe_shortcut", {"action": "switch_next_app"}),
        ("隐藏其他应用", "desktop.safe_shortcut", {"action": "hide_other_apps"}),
        ("隐藏其它应用", "desktop.safe_shortcut", {"action": "hide_other_apps"}),
        ("只显示当前应用", "desktop.safe_shortcut", {"action": "hide_other_apps"}),
        ("hide other apps", "desktop.safe_shortcut", {"action": "hide_other_apps"}),
        ("show only current app", "desktop.safe_shortcut", {"action": "hide_other_apps"}),
        ("当前窗口最大化", "desktop.safe_shortcut", {"action": "toggle_full_screen"}),
        ("maximize the current window", "desktop.safe_shortcut", {"action": "toggle_full_screen"}),
        ("show mission control", "desktop.safe_shortcut", {"action": "mission_control"}),
        ("show app windows", "desktop.safe_shortcut", {"action": "application_windows"}),
        ("show application windows", "desktop.safe_shortcut", {"action": "application_windows"}),
        ("spotlight search", "desktop.safe_shortcut", {"action": "spotlight_search"}),
        ("show emoji picker", "desktop.safe_shortcut", {"action": "emoji_picker"}),
        ("lock screen", "desktop.safe_shortcut", {"action": "lock_screen"}),
        ("show force quit applications", "desktop.safe_shortcut", {"action": "force_quit_dialog"}),
        ("Could you press Escape?", "desktop.safe_key", {"action": "escape", "repeat_count": 1}),
        ("Can you hit Tab?", "desktop.safe_key", {"action": "tab", "repeat_count": 1}),
        ("show desktop", "desktop.safe_key", {"action": "show_desktop", "repeat_count": 1}),
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

    hotkey_cases = (
        ("当前窗口按回车", {"key": "return", "modifiers": []}),
        ("前台按回车", {"key": "return", "modifiers": []}),
        ("press enter in current window", {"key": "return", "modifiers": []}),
        ("空格一下", {"key": "space", "modifiers": []}),
    )
    for prompt, tool_input in hotkey_cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "desktop.hotkey",
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == "desktop.hotkey"

    for prompt in ("退出当前应用", "关闭当前 app"):
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "desktop.quit_app",
                "input": {},
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == "desktop.quit_app"

    safe_hotkey_cases = (
        ("按 Command+L", "desktop.safe_shortcut", {"action": "focus_address_bar"}),
        ("你能帮我按Command L吗", "desktop.safe_shortcut", {"action": "focus_address_bar"}),
        ("Can you press Command L?", "desktop.safe_shortcut", {"action": "focus_address_bar"}),
        (
            "Could you open Chrome and press Command L?",
            "app.open_and_safe_shortcut",
            {"app_name": "Google Chrome", "action": "focus_address_bar"},
        ),
    )

    for prompt, tool_name, tool_input in safe_hotkey_cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == tool_name


def test_daily_desktop_entrypoint_routes_spotlight_search_to_shortcut_and_type() -> None:
    expected = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "spotlight_search"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
    ]
    for prompt in (
        "Spotlight 搜索 yachiyo",
        "打开 Spotlight 搜索 yachiyo",
        "用 Spotlight 搜索 yachiyo",
        "聚焦搜索 yachiyo",
        "打开聚焦搜索 yachiyo",
        "spotlight search yachiyo",
        "open Spotlight and search yachiyo",
    ):
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == expected
        assert daily_desktop_user_metadata(requests)["daily_desktop_tools"] == [
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
        ]

    assert daily_desktop_entrypoint_requests("打开聚焦搜索") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "spotlight_search"},
        }
    ]


def test_daily_desktop_entrypoint_routes_music_app_playback_questions_to_desktop_tools() -> None:
    cases = (
        ("打开网易云并播放", "media.music_app_open_and_play", {"app_name": "网易云音乐"}),
        ("可以帮我打开网易云并播放吗", "media.music_app_open_and_play", {"app_name": "网易云音乐"}),
        ("Could you launch Spotify and play music?", "media.music_app_open_and_play", {"app_name": "Spotify"}),
        ("能帮我播放 Apple Music 吗", "media.apple_music_open_and_play", {}),
        ("能不能直接播个 Apple Music", "media.apple_music_open_and_play", {}),
        ("把 Apple Music 打开然后播放", "media.apple_music_open_and_play", {}),
        ("Apple Music 随便播一首", "media.apple_music_open_and_play", {}),
        ("你能不能帮我播放音乐", "media.apple_music_open_and_play", {}),
        ("帮我在 Apple Music 播放点音乐", "media.apple_music_open_and_play", {}),
        ("打开音乐听听", "media.apple_music_open_and_play", {}),
        ("音乐听听", "media.apple_music_open_and_play", {}),
        ("打开音乐听一下", "media.apple_music_open_and_play", {}),
        ("can you play some music?", "media.apple_music_open_and_play", {}),
        ("put on some music", "media.apple_music_open_and_play", {}),
        ("把 Spotify 打开然后播放", "media.music_app_open_and_play", {"app_name": "Spotify"}),
        ("把网易云打开然后播放", "media.music_app_open_and_play", {"app_name": "网易云音乐"}),
        ("Spotify 随便放一首", "media.music_app_open_and_play", {"app_name": "Spotify"}),
        ("网易云给我放点歌", "media.music_app_open_and_play", {"app_name": "网易云音乐"}),
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

    assert daily_desktop_entrypoint_requests(
        "打开 Apple Music 并播放",
        allowed_tools=["media.apple_music_control"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "media.apple_music_control",
            "input": {"action": "play"},
        }
    ]


def test_daily_desktop_entrypoint_routes_music_control_language() -> None:
    cases = (
        ("播放继续", {"action": "play"}),
        ("跳过这首", {"action": "next"}),
        ("skip this song", {"action": "next"}),
        ("next media track", {"action": "next"}),
        ("previous media track", {"action": "previous"}),
        ("别放了", {"action": "pause"}),
        ("pause current media", {"action": "pause"}),
        ("resume playback", {"action": "play"}),
        ("关掉音乐", {"action": "pause"}),
    )

    for prompt, tool_input in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "media.system_control",
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == (
            "media.system_control"
        )

    for prompt, action in (
        ("Apple Music 暂停", "pause"),
        ("Music pause", "pause"),
        ("Music stop", "pause"),
        ("Music next", "next"),
        ("Apple Music next", "next"),
        ("Music previous", "previous"),
        ("Apple Music previous", "previous"),
        ("Music resume", "play"),
        ("Apple Music resume", "play"),
    ):
        assert daily_desktop_entrypoint_requests(prompt) == [
            {
                "protocol": "json_fallback",
                "tool": "media.apple_music_control",
                "input": {"action": action},
            }
        ]
    for prompt, app_name, action in (
        ("Spotify 暂停", "Spotify", "pause"),
        ("网易云下一首", "网易云音乐", "next"),
        ("QQ音乐上一首", "QQ音乐", "previous"),
        ("QQ Music next track", "QQ音乐", "next"),
    ):
        assert daily_desktop_entrypoint_requests(prompt) == [
            {
                "protocol": "json_fallback",
                "tool": "media.music_app_control",
                "input": {"app_name": app_name, "action": action},
            }
        ]

    for prompt in ("当前播放什么", "现在播放什么歌", "Apple Music 现在在播什么", "音乐状态"):
        status_requests = daily_desktop_entrypoint_requests(prompt)

        assert status_requests == [
            {
                "protocol": "json_fallback",
                "tool": "media.apple_music_status",
                "input": {},
            }
        ]
        assert daily_desktop_user_metadata(status_requests) == {
            "daily_desktop_intent": True,
            "daily_desktop_source": "daily_desktop_intent",
            "daily_desktop_planning_reason": "clear_daily_desktop_intent",
            "daily_desktop_tool": "media.apple_music_status",
            "daily_desktop_tools": ["media.apple_music_status"],
        }


def test_daily_desktop_entrypoint_routes_music_app_search_play_sequences() -> None:
    requests = daily_desktop_entrypoint_requests("打开 Spotify 搜索 Taylor Swift 并播放")

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Spotify", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Taylor Swift"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "media.music_app_open_and_play",
            "input": {"app_name": "Spotify"},
        },
    ]
    assert daily_desktop_user_metadata(requests)["daily_desktop_tools"] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "media.music_app_open_and_play",
    ]

    direct_play_requests = daily_desktop_entrypoint_requests("用 Spotify 播放 Taylor Swift")

    assert direct_play_requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Spotify", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Taylor Swift"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "media.music_app_open_and_play",
            "input": {"app_name": "Spotify"},
        },
    ]

    focus_requests = daily_desktop_entrypoint_requests("网易云音乐搜索周杰伦并播放")

    assert focus_requests[0] == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "网易云音乐", "action": "find"},
    }
    assert focus_requests[1]["input"] == {"text": "周杰伦"}

    open_direct_play_requests = daily_desktop_entrypoint_requests("打开网易云音乐播放周杰伦")

    assert open_direct_play_requests[0] == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "网易云音乐", "action": "find"},
    }
    assert open_direct_play_requests[1]["input"] == {"text": "周杰伦"}


def test_daily_desktop_entrypoint_routes_colloquial_music_queries_to_apple_music() -> None:
    cases = (
        ("放点周杰伦", {"query": "周杰伦"}),
        ("播点轻音乐", {"query": "轻音乐"}),
        ("来点轻音乐", {"query": "轻音乐"}),
        ("play some jazz", {"query": "jazz"}),
        ("play some Taylor Swift", {"query": "Taylor Swift"}),
        ("play Some Nights", {"query": "Some Nights"}),
        ("播个超时空辉夜姬", {"query": "超时空辉夜姬"}),
        ("put some jazz on Apple Music", {"query": "jazz"}),
        ("search Apple Music for Taylor Swift and play it", {"query": "Taylor Swift"}),
        ("Apple Music play Taylor Swift", {"query": "Taylor Swift"}),
        ("play Apple Music Taylor Swift", {"query": "Taylor Swift"}),
        ("打开 Apple Music 搜索超时空辉夜姬并播放", {"query": "超时空辉夜姬"}),
        ("open Apple Music and search Space Oddity and play it", {"query": "Space Oddity"}),
        ("超时空辉夜姬播放", {"query": "超时空辉夜姬"}),
        ("周杰伦播放一下", {"query": "周杰伦"}),
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
        ("放大音量", {"action": "up"}),
        ("把音量放大", {"action": "up"}),
        ("声音放大一点", {"action": "up"}),
        ("Apple Music 放大音量", {"action": "up"}),
        ("缩小音量", {"action": "down"}),
        ("把音量缩小", {"action": "down"}),
        ("Apple Music 缩小音量", {"action": "down"}),
        ("调到35音量", {"action": "set", "level": 35}),
        ("设成 35 音量", {"action": "set", "level": 35}),
        ("volume 35", {"action": "set", "level": 35}),
        ("set sound to 35", {"action": "set", "level": 35}),
        ("声音关掉", {"action": "mute"}),
        ("别出声", {"action": "mute"}),
        ("sound up", {"action": "up"}),
        ("sound down", {"action": "down"}),
        ("查看当前音量", {"action": "status"}),
        ("show current volume", {"action": "status"}),
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

    for prompt in (
        "静音当前标签页",
        "把当前标签页静音",
        "取消静音当前标签页",
        "mute current tab",
        "mute this tab",
        "unmute current tab",
    ):
        assert daily_desktop_entrypoint_requests(prompt) == []

    assert daily_desktop_entrypoint_requests("当前标签页是什么") == [
        {
            "protocol": "json_fallback",
            "tool": "browser.current_page",
            "input": {},
        }
    ]

    brightness_cases = (
        ("亮一点", {"action": "up", "step": 2}),
        ("再亮一点", {"action": "up", "step": 2}),
        ("亮度大一点", {"action": "up", "step": 2}),
        ("暗一点", {"action": "down", "step": 2}),
        ("调暗一点", {"action": "down", "step": 2}),
        ("亮度小一点", {"action": "down", "step": 2}),
    )
    for prompt, tool_input in brightness_cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "system.brightness",
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == "system.brightness"

    display_sleep_cases = ("关闭屏幕", "让显示器睡眠", "息屏一下", "turn off the display")
    for prompt in display_sleep_cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "system.display_sleep",
                "input": {},
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == "system.display_sleep"

    assert daily_desktop_entrypoint_requests("sleep my Mac") == []

    screen_saver_cases = ("启动屏幕保护程序", "打开屏保", "start screen saver")
    for prompt in screen_saver_cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "system.screen_saver_start",
                "input": {},
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == "system.screen_saver_start"

    assert daily_desktop_entrypoint_requests("打开屏幕保护程序设置") == [
        {
            "protocol": "json_fallback",
            "tool": "system.settings_open",
            "input": {"target": "屏幕保护程序"},
        }
    ]
    assert daily_desktop_entrypoint_requests("漂亮一点") == []


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
