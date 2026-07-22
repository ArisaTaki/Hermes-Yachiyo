"""Regression coverage for same-app search verification ordering."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.action_targets import action_target_matches
from apps.shell.agent.runtime.goal_runtime import (
    runtime_goal_assessment,
    runtime_goal_contract,
)
from apps.shell.agent.runtime.tool_execution import _post_action_verification_request
from apps.shell.yachiyo_agent.planner_execution import (
    planner_full_plan_execution_tool_requests,
    planner_tool_requests_for_decision,
)
from apps.shell.yachiyo_agent.runtime_execution import (
    runtime_execution_envelope_from_decision,
)
from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner


_APP_SEARCH_TOOLS = [
    "desktop.inspect_app",
    "desktop.list_apps",
    "app.open",
    "app.focus",
    "app.open_and_safe_shortcut",
    "app.focus_and_safe_shortcut",
    "app.open_and_click_ui_element",
    "app.focus_and_click_ui_element",
    "desktop.safe_shortcut",
    "desktop.safe_type_text",
    "desktop.search_submit",
    "desktop.click_ui_element",
    "desktop.ui_elements",
    "desktop.active_window",
]


def _notes_search_requests() -> list[dict]:
    decision = RuntimePlanner().decision(
        "打开 Notes，然后搜索 hello",
        allowed_tools=_APP_SEARCH_TOOLS,
    )
    return planner_tool_requests_for_decision(decision, _APP_SEARCH_TOOLS)


def test_same_app_search_does_not_auto_verify_after_combined_open_and_focus_shortcut() -> None:
    requests = _notes_search_requests()
    prepare_index = next(
        index
        for index, request in enumerate(requests)
        if request["tool"] == "app.open_and_safe_shortcut"
    )

    auto_verification = _post_action_verification_request(
        "app.open_and_safe_shortcut",
        requests[prepare_index],
        {"ok": True, "data": {"app_name": "Notes"}},
        allowed_tools=_APP_SEARCH_TOOLS,
        remaining_requests=requests[prepare_index + 1 :],
        active_window_target=None,
    )

    assert auto_verification == {}


def test_same_app_search_keeps_final_verification_for_the_operation_chain() -> None:
    requests = _notes_search_requests()

    assert [request["tool"] for request in requests] == [
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.ui_elements",
    ]
    verification = requests[-1]
    assert verification["runtime_stage"] == "verify"
    assert [
        request["requires_post_action_verification"]
        for request in requests[1:]
    ] == [False, False, True, False]
    assert [
        target["step_id"] for target in verification["task_verification_targets"]
    ] == ["submit-app-search"]


def test_open_and_find_is_a_submitted_verified_app_search() -> None:
    decision = RuntimePlanner().decision(
        "打开 Finder 找下载文件",
        allowed_tools=_APP_SEARCH_TOOLS,
    )
    requests = planner_tool_requests_for_decision(decision, _APP_SEARCH_TOOLS)

    assert [request["tool"] for request in requests] == [
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.ui_elements",
    ]
    assert requests[-1]["runtime_stage"] == "verify"
    assert requests[-1]["depends_on"] == ["submit-app-search"]

    contract = decision.plan.task_core.goal_contract
    assert contract is not None
    criterion = contract.criteria[0]
    assert criterion.source_step_ids == ["submit-app-search"]
    assert criterion.verifier_step_ids == ["verify-desktop-result"]
    assert criterion.expected["target"] == {
        "kind": "desktop_app",
        "action": "submit_ui",
        "app_name": "Finder",
        "selection_source": "direct_app_name",
        "query": "下载文件",
        "target": "搜索",
        "role_filter": "text",
    }

    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=_APP_SEARCH_TOOLS,
        full_plan=True,
    )
    assert envelope is not None
    submit = next(
        request for request in envelope.requests if request.step_id == "submit-app-search"
    )
    assert submit.action_target == {
        **criterion.expected["target"],
        "selection_query": "Finder",
        "step_id": "submit-app-search",
    }


def test_app_search_goal_rejects_type_without_submit_and_wrong_search_target() -> None:
    decision = RuntimePlanner().decision(
        "打开 Finder 找下载文件",
        allowed_tools=_APP_SEARCH_TOOLS,
    )
    contract = runtime_goal_contract(
        run_id="run-finder-search",
        runtime_execution_envelope={
            "task_core": decision.plan.task_core.model_dump(),  # type: ignore[union-attr]
        },
        runtime_execution_metadata=None,
        messages=[{"role": "user", "content": "打开 Finder 找下载文件"}],
        timeline=[],
    )
    assert contract is not None
    typed_only = runtime_goal_assessment(
        contract,
        [
            {
                "event": "agent.tool.call",
                "run_id": contract.run_id,
                "detail": "desktop.safe_type_text",
                "tool_call_id": "type-only",
                "step_id": "type-app-search-query",
                "capability_id": "desktop.ui_operation",
                "action_target": {
                    "kind": "desktop_app",
                    "action": "type_ui",
                    "app_name": "Finder",
                    "selection_source": "direct_app_name",
                    "query": "下载文件",
                    "target": "搜索",
                    "role_filter": "text",
                },
                "result": {"ok": True, "postcondition_verified": True},
            }
        ],
    )

    assert typed_only.completed is False
    expected_target = contract.criteria[0].expected["target"]
    assert action_target_matches(
        expected_target,
        {**expected_target, "target": "地址栏"},
        capability_ids=("desktop.ui_operation",),
        source_step_id="submit-app-search",
    ) is False


def test_explicit_search_field_click_is_observed_and_approval_gated_before_typing() -> None:
    decision = RuntimePlanner().decision(
        "Chrome 点击搜索框输入 yachiyo",
        allowed_tools=_APP_SEARCH_TOOLS,
    )
    steps = decision.plan.tool_plan.steps

    assert [step.step_id for step in steps] == [
        "inspect-app-search-field",
        "focus-app-search-field",
        "type-app-search-query",
        "verify-desktop-result",
    ]
    assert steps[0].tool_name == "desktop.inspect_app"
    assert steps[0].approval_required is False
    assert steps[0].input_preview == {
        "app_name": "Google Chrome",
        "open_if_needed": False,
        "focus": True,
        "role_filter": "text",
        "limit": 80,
    }
    click = steps[1]
    assert click.tool_name == "app.focus_and_click_ui_element"
    assert click.input_preview == {
        "app_name": "Google Chrome",
        "target": "搜索",
        "role_filter": "text",
        "click_count": 1,
        "limit": 80,
    }
    assert click.depends_on == ["inspect-app-search-field"]
    assert click.approval_required is True
    assert click.risk_level == "medium"
    assert steps[2].depends_on == ["focus-app-search-field"]
    assert steps[-1].depends_on == ["type-app-search-query"]

    requests = planner_tool_requests_for_decision(decision, _APP_SEARCH_TOOLS)
    assert [request["tool"] for request in requests] == [
        "desktop.inspect_app",
        "app.focus_and_click_ui_element",
        "desktop.safe_type_text",
        "desktop.ui_elements",
    ]
    assert requests[1]["approval_required"] is True
    assert all(
        request["tool"] not in {"desktop.safe_shortcut", "app.focus_and_safe_shortcut"}
        for request in requests
    )
    assert requests[-1]["task_verification_targets"][0]["step_id"] == (
        "type-app-search-query"
    )

    contract = decision.plan.task_core.goal_contract
    assert contract is not None
    criterion = contract.criteria[0]
    assert criterion.source_step_ids == ["type-app-search-query"]
    assert criterion.verifier_step_ids == ["verify-desktop-result"]
    assert criterion.expected["target"] == {
        "kind": "desktop_app",
        "action": "type_ui",
        "app_name": "Google Chrome",
        "selection_source": "direct_app_name",
        "query": "yachiyo",
        "target": "搜索",
        "role_filter": "text",
    }


def test_explicit_search_field_click_never_degrades_to_find_shortcut() -> None:
    allowed = [
        "desktop.list_apps",
        "app.focus_and_safe_shortcut",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "desktop.ui_elements",
    ]
    decision = RuntimePlanner().decision(
        "Chrome 点击搜索框输入 yachiyo",
        allowed_tools=allowed,
    )
    requests = planner_tool_requests_for_decision(decision, allowed)

    assert all(
        not (
            request["tool"] in {"desktop.safe_shortcut", "app.focus_and_safe_shortcut"}
            and request.get("input", {}).get("action") == "find"
        )
        for request in requests
    )
    assert all(request["tool"] != "desktop.safe_type_text" for request in requests)


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


def test_named_app_field_with_url_shaped_text_stays_a_desktop_ui_operation() -> None:
    allowed_tools = [
        "desktop.inspect_app",
        "app.open_and_type_into_ui_element",
        "desktop.ui_elements",
    ]

    decision = RuntimePlanner().decision(
        "打开 Chrome 并在名为 URL 的输入框输入 github.com",
        allowed_tools=allowed_tools,
    )
    requests = planner_tool_requests_for_decision(decision, allowed_tools)

    assert decision.selected_intent.kind == "desktop_operation"
    assert [request["tool"] for request in requests] == [
        "desktop.inspect_app",
        "app.open_and_type_into_ui_element",
        "desktop.ui_elements",
    ]


def test_chinese_capture_verb_routes_to_current_browser_page_screenshot() -> None:
    allowed_tools = ["browser.screenshot"]

    decision = RuntimePlanner().decision(
        "截取当前网页",
        allowed_tools=allowed_tools,
    )
    requests = planner_tool_requests_for_decision(decision, allowed_tools)

    assert decision.selected_intent.kind == "web_research"
    assert [request["tool"] for request in requests] == ["browser.screenshot"]


def test_named_app_switch_routes_to_focus_without_confusing_app_cycle_shortcuts() -> None:
    allowed_tools = ["desktop.list_apps", "app.focus", "desktop.active_window"]

    decision = RuntimePlanner().decision(
        "切换到 Slack",
        allowed_tools=allowed_tools,
    )
    requests = planner_tool_requests_for_decision(decision, allowed_tools)

    assert decision.selected_intent.kind == "desktop_operation"
    assert [request["tool"] for request in requests] == [
        "desktop.list_apps",
        "app.focus",
        "desktop.active_window",
    ]
    assert RuntimePlanner().decision(
        "切换到下一个应用",
        allowed_tools=["desktop.safe_shortcut"],
    ).selected_intent.inputs.get("app_management_hint") is None


def test_browser_coordinate_type_does_not_invent_an_app_write_followup() -> None:
    allowed_tools = ["browser.type_text", "desktop.list_apps", "app.focus"]

    decision = RuntimePlanner().decision(
        "在网页坐标 120 240 输入 hello",
        allowed_tools=allowed_tools,
    )
    requests = planner_tool_requests_for_decision(decision, allowed_tools)

    assert decision.selected_intent.kind == "web_research"
    assert "target_app_hint" not in decision.selected_intent.inputs
    assert [request["tool"] for request in requests] == ["browser.type_text"]


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


_GENERIC_SELECTED_APP_SEARCH_TOOLS = [
    "desktop.list_apps",
    "app.open",
    "app.open_and_safe_shortcut",
    "desktop.safe_type_text",
    "desktop.search_submit",
    "desktop.ui_elements",
]


def _decision_with_tool_plan_steps(decision: Any, steps: list[Any]) -> Any:
    tool_plan = decision.plan.tool_plan.model_copy(update={"steps": steps})
    plan = decision.plan.model_copy(update={"tool_plan": tool_plan})
    return decision.model_copy(update={"plan": plan})


def _generic_selected_app_search_without_separate_open_step() -> Any:
    decision = RuntimePlanner().decision(
        "帮我打开一个设计工具，搜索 logo 模板",
        allowed_tools=_GENERIC_SELECTED_APP_SEARCH_TOOLS,
    )
    steps = []
    for step in decision.plan.tool_plan.steps:
        if step.step_id == "open-selected-discovered-app":
            continue
        if step.step_id == "focus-app-search-field":
            step = step.model_copy(
                update={"depends_on": ["discover_apps-desktop-state"]}
            )
        steps.append(step)
    return _decision_with_tool_plan_steps(decision, steps)


def test_runtime_resolvable_selected_app_consumers_do_not_trigger_model_fallback() -> None:
    decision = _generic_selected_app_search_without_separate_open_step()

    requests = planner_tool_requests_for_decision(
        decision,
        _GENERIC_SELECTED_APP_SEARCH_TOOLS,
    )

    assert [request["tool"] for request in requests] == [
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.ui_elements",
    ]
    assert requests[1]["input"] == {
        "app_name": "<selected app from desktop.list_apps>",
        "action": "find",
        "selection_source": "desktop.list_apps",
        "query": "image",
    }
    assert not any(request.get("continue_to_model") for request in requests)


def test_unresolved_selected_app_consumer_still_triggers_model_fallback() -> None:
    decision = _generic_selected_app_search_without_separate_open_step()
    steps = []
    for step in decision.plan.tool_plan.steps:
        if step.step_id == "focus-app-search-field":
            unresolved_payload = dict(step.input_preview)
            unresolved_payload.pop("query")
            step = step.model_copy(update={"input_preview": unresolved_payload})
        steps.append(step)
    decision = _decision_with_tool_plan_steps(decision, steps)

    requests = planner_tool_requests_for_decision(
        decision,
        _GENERIC_SELECTED_APP_SEARCH_TOOLS,
    )

    assert [request["tool"] for request in requests] == ["desktop.list_apps"]
    assert requests[0]["continue_to_model"] is True


def test_selected_app_plan_needing_model_reasoning_still_triggers_fallback() -> None:
    decision = _generic_selected_app_search_without_separate_open_step()
    selected_intent = decision.selected_intent.model_copy(
        update={
            "inputs": {
                **dict(decision.selected_intent.inputs),
                "model_generated_content_hint": {"description": "create a logo"},
            }
        }
    )
    decision = decision.model_copy(update={"selected_intent": selected_intent})

    requests = planner_tool_requests_for_decision(
        decision,
        _GENERIC_SELECTED_APP_SEARCH_TOOLS,
    )

    assert [request["tool"] for request in requests] == ["desktop.list_apps"]
    assert requests[0]["continue_to_model"] is True
