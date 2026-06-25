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
        ("隐藏当前窗口", "desktop.minimize_window", {}),
        ("隐藏前台窗口", "desktop.minimize_window", {}),
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
            "desktop.hotkey",
            {"key": "f", "modifiers": ["control", "command"]},
        ),
        (
            "maximize the current window",
            "desktop.hotkey",
            {"key": "f", "modifiers": ["control", "command"]},
        ),
        (
            "切换到上一个应用",
            "desktop.hotkey",
            {"key": "tab", "modifiers": ["command"]},
        ),
        (
            "switch to previous app",
            "desktop.hotkey",
            {"key": "tab", "modifiers": ["command"]},
        ),
        (
            "切到下一个应用",
            "desktop.hotkey",
            {"key": "tab", "modifiers": ["command"]},
        ),
        (
            "switch to next app",
            "desktop.hotkey",
            {"key": "tab", "modifiers": ["command"]},
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

    assert daily_desktop_entrypoint_requests("在当前输入框输入 hello") == [
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
    assert daily_desktop_entrypoint_requests("提交当前搜索") == [
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}}
    ]
    assert daily_desktop_entrypoint_requests("press enter to search") == [
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}}
    ]

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
            "tool": "desktop.hotkey",
            "input": {"key": "l", "modifiers": ["command"]},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    assert daily_desktop_entrypoint_requests("copy current page link") == copy_link_requests
    assert daily_desktop_entrypoint_requests("把当前网址放到剪贴板") == copy_link_requests
    assert daily_desktop_entrypoint_requests("当前页地址复制一下") == copy_link_requests
    assert daily_desktop_user_metadata(copy_link_requests) == {
        "daily_desktop_intent": True,
        "daily_desktop_source": "daily_desktop_intent",
        "daily_desktop_planning_reason": "clear_daily_desktop_intent",
        "daily_desktop_tool": "desktop.hotkey",
        "daily_desktop_tools": ["desktop.hotkey", "desktop.safe_shortcut"],
    }

    assert daily_desktop_entrypoint_requests("当前网页是什么") == [
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
            "打开下载目录里的最新文件",
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
            "打开用户目录",
            "desktop.open_path",
            {"path": "~"},
        ),
        (
            "open user directory",
            "desktop.open_path",
            {"path": "~"},
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


def test_daily_desktop_entrypoint_routes_app_browser_search_language() -> None:
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


def test_daily_desktop_entrypoint_routes_notes_and_time_first_reminders() -> None:
    tomorrow_0900 = f"{(date.today() + timedelta(days=1)).isoformat()}T09:00"
    tomorrow_1500 = f"{(date.today() + timedelta(days=1)).isoformat()}T15:00"
    tomorrow_1600 = f"{(date.today() + timedelta(days=1)).isoformat()}T16:00"

    assert daily_desktop_entrypoint_requests("帮我新建备忘录：明天买牛奶") == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "明天买牛奶"},
        }
    ]
    assert daily_desktop_entrypoint_requests("明天上午九点提醒我开会") == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "开会", "due_at": tomorrow_0900},
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


def test_daily_desktop_entrypoint_routes_colloquial_safe_scroll_language() -> None:
    cases = (
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
        ("你能帮我全选吗", "desktop.safe_shortcut", {"action": "select_all"}),
        ("你可以帮我撤销吗", "desktop.safe_shortcut", {"action": "undo"}),
        ("切到下一个窗口", "desktop.safe_shortcut", {"action": "next_window"}),
        ("切到上一个窗口", "desktop.safe_shortcut", {"action": "previous_window"}),
        ("打开任务控制中心", "desktop.safe_shortcut", {"action": "mission_control"}),
        ("显示当前应用窗口", "desktop.safe_shortcut", {"action": "application_windows"}),
        ("显示前台应用窗口", "desktop.safe_shortcut", {"action": "application_windows"}),
        ("打开聚焦搜索", "desktop.safe_shortcut", {"action": "spotlight_search"}),
        ("打开 Spotlight", "desktop.safe_shortcut", {"action": "spotlight_search"}),
        ("打开 emoji 面板", "desktop.safe_shortcut", {"action": "emoji_picker"}),
        ("锁屏", "desktop.safe_shortcut", {"action": "lock_screen"}),
        ("打开强制退出窗口", "desktop.safe_shortcut", {"action": "force_quit_dialog"}),
        ("你能帮我按一下Escape吗", "desktop.safe_key", {"action": "escape", "repeat_count": 1}),
        ("你可以帮我按Tab吗", "desktop.safe_key", {"action": "tab", "repeat_count": 1}),
        ("显示桌面", "desktop.safe_key", {"action": "show_desktop", "repeat_count": 1}),
        ("当前窗口按 Command V", "desktop.safe_shortcut", {"action": "paste"}),
        ("Can you copy?", "desktop.safe_shortcut", {"action": "copy"}),
        ("Could you paste?", "desktop.safe_shortcut", {"action": "paste"}),
        ("Would you select all please?", "desktop.safe_shortcut", {"action": "select_all"}),
        ("switch to next window", "desktop.safe_shortcut", {"action": "next_window"}),
        ("switch to previous window", "desktop.safe_shortcut", {"action": "previous_window"}),
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
        ("能不能直接播个 Apple Music", "media.apple_music_open_and_play", {}),
        ("put on some music", "media.apple_music_open_and_play", {}),
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
        ("打开 Apple Music 搜索超时空辉夜姬并播放", {"query": "超时空辉夜姬"}),
        ("open Apple Music and search Space Oddity and play it", {"query": "Space Oddity"}),
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

    brightness_cases = (
        ("亮一点", {"action": "up", "step": 2}),
        ("再亮一点", {"action": "up", "step": 2}),
        ("暗一点", {"action": "down", "step": 2}),
        ("调暗一点", {"action": "down", "step": 2}),
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
