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


def test_approval_entrypoint_preserves_requests_after_first_approval() -> None:
    requests = [
        {
            "tool": "desktop.hotkey",
            "input": {"key": "l", "modifiers": ["command"]},
            "approval_required": True,
            "risk_level": "medium",
        },
        {
            "tool": "desktop.safe_type_text",
            "input": {"text": "github.com"},
            "risk_level": "low",
        },
        {
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
            "approval_required": True,
            "risk_level": "high",
        },
    ]

    selected = daily_desktop_approval_or_submit_entrypoint_requests(requests)

    assert selected == requests


def test_approval_entrypoint_preserves_only_ordered_dependency_ancestors() -> None:
    requests = [
        {
            "tool": "desktop.running_apps",
            "input": {},
            "step_id": "discover",
        },
        {
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "step_id": "paste",
            "depends_on": ["discover"],
        },
        {
            "tool": "desktop.read_ui",
            "input": {},
            "step_id": "unrelated-observation",
        },
        {
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "step_id": "send",
            "depends_on": ["paste"],
            "approval_required": True,
            "risk_level": "high",
        },
        {
            "tool": "desktop.ui_elements",
            "input": {},
            "step_id": "verify",
            "depends_on": ["send"],
            "runtime_stage": "verify",
            "continue_to_model": True,
        },
        {
            "tool": "artifact.write",
            "input": {"path": "research-summary.md"},
            "continue_to_model": True,
        },
    ]

    selected = daily_desktop_approval_or_submit_entrypoint_requests(
        requests,
        text="在当前输入框粘贴并发送",
    )

    assert [request["step_id"] for request in selected] == [
        "discover",
        "paste",
        "send",
        "verify",
    ]
    assert [request["tool"] for request in selected] == [
        "desktop.running_apps",
        "desktop.safe_shortcut",
        "desktop.submit_foreground",
        "desktop.ui_elements",
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
