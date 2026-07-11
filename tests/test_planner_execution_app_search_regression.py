"""Regression coverage for same-app search verification ordering."""

from __future__ import annotations

from apps.shell.agent.runtime.tool_execution import _post_action_verification_request
from apps.shell.yachiyo_agent.planner_execution import (
    planner_full_plan_execution_tool_requests,
    planner_tool_requests_for_decision,
)
from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner


_APP_SEARCH_TOOLS = [
    "desktop.list_apps",
    "app.open",
    "app.focus",
    "app.open_and_safe_shortcut",
    "desktop.safe_shortcut",
    "desktop.safe_type_text",
    "desktop.search_submit",
    "desktop.ui_elements",
    "desktop.active_window",
]


def _notes_search_requests() -> list[dict]:
    decision = RuntimePlanner().decision(
        "打开 Notes，然后搜索 hello",
        allowed_tools=_APP_SEARCH_TOOLS,
    )
    return planner_tool_requests_for_decision(decision, _APP_SEARCH_TOOLS)


def test_same_app_search_does_not_auto_verify_after_open() -> None:
    requests = _notes_search_requests()
    open_index = next(
        index for index, request in enumerate(requests) if request["tool"] == "app.open"
    )

    auto_verification = _post_action_verification_request(
        "app.open",
        requests[open_index],
        {"ok": True, "data": {"app_name": "Notes"}},
        allowed_tools=_APP_SEARCH_TOOLS,
        remaining_requests=requests[open_index + 1 :],
        active_window_target=None,
    )

    assert auto_verification == {}


def test_same_app_search_keeps_final_verification_for_the_operation_chain() -> None:
    requests = _notes_search_requests()

    assert [request["tool"] for request in requests] == [
        "desktop.list_apps",
        "app.open",
        "app.focus",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.ui_elements",
    ]
    verification = requests[-1]
    assert verification["runtime_stage"] == "verify"
    assert all(
        request["requires_post_action_verification"] is False
        for request in requests[1:5]
    )
    assert requests[5]["requires_post_action_verification"] is True
    assert [
        target["step_id"] for target in verification["task_verification_targets"]
    ] == ["submit-app-search"]


def test_standalone_app_open_keeps_discover_operate_verify() -> None:
    allowed_tools = ["desktop.list_apps", "app.open", "desktop.active_window"]
    decision = RuntimePlanner().decision(
        "打开 PixelForge",
        allowed_tools=allowed_tools,
    )

    requests = planner_tool_requests_for_decision(decision, allowed_tools)

    assert [request["runtime_stage"] for request in requests] == [
        "discover",
        "operate",
        "verify",
    ]
    assert requests[1]["requires_post_action_verification"] is True
    assert requests[-1]["task_verification_targets"][0]["step_id"] == (
        "open-or-focus-app"
    )


def test_deferred_verification_does_not_cross_app_switch() -> None:
    requests = planner_full_plan_execution_tool_requests(
        [
            {
                "tool": "app.open",
                "input": {"app_name": "Notes"},
                "step_id": "open-notes",
                "requires_post_action_verification": True,
            },
            {
                "tool": "app.open",
                "input": {"app_name": "Safari"},
                "step_id": "open-safari",
                "depends_on": ["open-notes"],
                "requires_post_action_verification": True,
            },
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "step_id": "type-safari",
                "depends_on": ["open-safari"],
                "requires_post_action_verification": True,
            },
            {
                "tool": "desktop.ui_elements",
                "input": {"app_name": "Safari"},
                "step_id": "verify-safari",
                "depends_on": ["type-safari"],
                "runtime_stage": "verify",
            },
        ],
        ["app.open", "desktop.safe_type_text", "desktop.ui_elements"],
    )
    requests_by_step = {request["step_id"]: request for request in requests}

    assert (
        requests_by_step["open-notes"]["requires_post_action_verification"] is True
    )
    assert (
        requests_by_step["open-safari"]["requires_post_action_verification"] is False
    )
    assert (
        requests_by_step["type-safari"]["requires_post_action_verification"] is True
    )


def test_deferred_verification_does_not_cross_app_agnostic_shortcut() -> None:
    requests = planner_full_plan_execution_tool_requests(
        [
            {
                "tool": "app.open",
                "input": {"app_name": "Notes"},
                "step_id": "open-notes",
                "requires_post_action_verification": True,
            },
            {
                "tool": "desktop.safe_shortcut",
                "input": {"action": "spotlight_search"},
                "step_id": "open-spotlight",
                "depends_on": ["open-notes"],
                "requires_post_action_verification": True,
            },
            {
                "tool": "desktop.ui_elements",
                "input": {"app_name": "Notes"},
                "step_id": "verify-notes",
                "depends_on": ["open-spotlight"],
                "runtime_stage": "verify",
            },
        ],
        ["app.open", "desktop.safe_shortcut", "desktop.ui_elements"],
    )
    requests_by_step = {request["step_id"]: request for request in requests}

    assert requests_by_step["open-notes"]["requires_post_action_verification"] is True
    assert requests_by_step["open-spotlight"]["requires_post_action_verification"] is True
