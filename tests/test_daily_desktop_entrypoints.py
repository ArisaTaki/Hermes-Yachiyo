from apps.shell.yachiyo_agent.daily_desktop import (
    daily_desktop_approval_or_submit_entrypoint_requests,
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
