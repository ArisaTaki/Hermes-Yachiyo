from apps.shell.yachiyo_agent.daily_desktop import (
    daily_desktop_approval_or_submit_entrypoint_requests,
    daily_desktop_safe_direct_entrypoint_requests,
)


def test_approval_entrypoint_preserves_prerequisite_open_without_planner_noise() -> None:
    requests = [
        {
            "tool": "desktop.open_app",
            "input": {
                "app_name": "Music",
                "query": "apple music",
                "selection_source": "alias",
            },
        },
        {
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
            "approval_required": True,
            "risk_level": "high",
        },
    ]

    selected = daily_desktop_approval_or_submit_entrypoint_requests(requests)

    assert selected == [
        {
            "tool": "desktop.open_app",
            "input": {"app_name": "Music"},
            "requires_post_action_verification": False,
        },
        {
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
            "approval_required": True,
            "risk_level": "high",
        },
    ]


def test_approval_entrypoint_skips_redundant_system_ui_confirm() -> None:
    requests = [
        {"tool": "desktop.open_app", "input": {"app_name": "Control Center"}},
        {
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
            "approval_required": True,
            "risk_level": "high",
        },
    ]

    selected = daily_desktop_approval_or_submit_entrypoint_requests(requests)

    assert selected == [
        {
            "tool": "desktop.open_app",
            "input": {"app_name": "Control Center"},
            "requires_post_action_verification": False,
        }
    ]


def test_submit_foreground_entrypoint_requires_approval() -> None:
    selected = daily_desktop_approval_or_submit_entrypoint_requests(
        [],
        text="submit the current form",
    )

    assert selected == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "submit"},
            "source": "runtime_planner",
            "planning_reason": "planner_submit_foreground_entrypoint",
            "approval_required": True,
            "risk_level": "high",
        }
    ]


def test_safe_direct_entrypoint_allows_discover_open_verify_app_chain() -> None:
    requests = [
        {
            "tool": "desktop.list_apps",
            "input": {"query": "Linear", "limit": 20},
            "approval_required": False,
            "risk_level": "low",
        },
        {
            "tool": "app.open",
            "input": {"app_name": "Linear"},
            "approval_required": False,
            "risk_level": "low",
        },
        {
            "tool": "desktop.active_window",
            "input": {},
            "approval_required": False,
            "risk_level": "low",
            "continue_to_model": True,
            "runtime_stage": "verify",
        },
    ]

    selected = daily_desktop_safe_direct_entrypoint_requests(requests)

    assert [request["tool"] for request in selected] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]


def test_safe_direct_entrypoint_blocks_keyboard_mouse_capture_tools() -> None:
    for tool_name, payload in (
        ("desktop.safe_type_text", {"text": "hello"}),
        ("desktop.safe_click", {"x": 10, "y": 10}),
        ("desktop.safe_shortcut", {"action": "new_tab"}),
        ("app.open_and_safe_type_text", {"app_name": "Notes", "text": "hello"}),
    ):
        selected = daily_desktop_safe_direct_entrypoint_requests(
            [
                {
                    "tool": tool_name,
                    "input": payload,
                    "approval_required": False,
                    "risk_level": "low",
                }
            ]
        )

        assert selected == []
