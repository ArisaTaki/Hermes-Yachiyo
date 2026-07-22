"""Focused desktop follow-up planning coverage."""

from __future__ import annotations

from apps.shell.yachiyo_agent.desktop_plan_hints import (
    app_control_mode,
    click_target_hint,
    desktop_action_requested,
    desktop_app_control_only_negated,
    safe_type_text_hint,
    standalone_safe_type_text_hint,
    type_into_ui_hint,
)
from apps.shell.yachiyo_agent.planner_execution import planner_direct_tool_requests
from apps.shell.yachiyo_agent.runtime_planner import (
    RuntimePlanner,
    _speech_act_strip_unauthorized_contextual_tails,
)


def test_type_text_hint_strips_return_key_followup() -> None:
    assert safe_type_text_hint("在当前输入框输入 hello 并按回车") == "hello"
    assert safe_type_text_hint("type hello and press enter") == "hello"
    assert click_target_hint("在 FoobarApp 输入 hello 并按回车") is None


def test_runtime_planner_uses_submit_fallback_for_return_after_typing() -> None:
    decision = RuntimePlanner().decision(
        "在 FoobarApp 输入 hello 并按回车",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.ui_elements",
            "desktop.safe_type_text",
            "desktop.submit_foreground",
        ],
    )

    steps = {step.step_id: step for step in decision.plan.tool_plan.steps}
    type_step = steps["operate-foreground-ui"]
    return_step = steps["operate-foreground-ui-followup-return"]

    assert type_step.tool_name == "desktop.safe_type_text"
    assert type_step.input_preview == {"text": "hello"}
    assert return_step.tool_name == "desktop.submit_foreground"
    assert return_step.input_preview == {"action": "confirm"}
    assert return_step.status == "planned"
    assert return_step.approval_required is True
    assert decision.plan.tool_plan.missing_capabilities == []


def test_negated_desktop_actions_do_not_become_execution_hints() -> None:
    assert click_target_hint("打开计算器，不要点击任何按钮") is None
    assert click_target_hint("Open Calculator without clicking any button") is None
    assert type_into_ui_hint("打开计算器，不要在搜索框输入任何内容") is None
    assert safe_type_text_hint("不要输入 hello") == ""
    assert standalone_safe_type_text_hint("不要输入 hello") == ""
    assert app_control_mode("只在后台打开计算器，不要切换焦点") == "open"
    assert app_control_mode("能不能切到 Slack 一下") == "focus"


def test_focus_request_question_does_not_mask_subject_negation() -> None:
    assert desktop_action_requested("能不能切到 Slack", "focus") is True
    assert desktop_action_requested("可不可以切到 Slack", "focus") is True
    assert desktop_action_requested("功能不能切到 Slack", "focus") is False
    assert desktop_action_requested("这个功能不能切到 Slack", "focus") is False


def test_english_inability_phrases_remain_negated_focus_actions() -> None:
    assert desktop_action_requested("Cannot switch to Slack", "focus") is False
    assert desktop_action_requested("Can not switch to Slack", "focus") is False
    assert desktop_action_requested("Can't switch to Slack", "focus") is False
    assert desktop_action_requested("Can’t switch to Slack", "focus") is False


def test_app_control_negation_helper_preserves_real_requests() -> None:
    assert desktop_app_control_only_negated("不能切到 Slack") is True
    assert desktop_app_control_only_negated("功能不能打开 Slack") is True
    assert desktop_app_control_only_negated("Cannot open Slack") is True
    assert desktop_app_control_only_negated("能不能切到 Slack") is False
    assert desktop_app_control_only_negated("可不可以打开 Slack") is False
    assert desktop_app_control_only_negated(
        "Open Calculator in the background. Do not type, click, or switch focus."
    ) is False


def test_polite_focus_requests_still_plan_focus_not_open() -> None:
    allowed_tools = ["desktop.list_apps", "desktop.verify", "app.open", "app.focus"]

    for prompt in (
        "能不能切到 Slack 一下",
        "可不可以切到 Slack",
        "请问一下能不能切到 Slack",
        "麻烦问一下能不能切到 Slack",
    ):
        decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
        plan_tools = [step.tool_name for step in decision.plan.tool_plan.steps]
        direct_tools = [
            str(request.get("tool") or "")
            for request in planner_direct_tool_requests(prompt, allowed_tools)
        ]

        assert plan_tools == ["desktop.list_apps", "app.focus", "desktop.verify"]
        assert direct_tools == plan_tools


def test_purely_negated_app_control_never_falls_back_to_open() -> None:
    allowed_tools = [
        "desktop.list_apps",
        "desktop.running_apps",
        "desktop.verify",
        "app.open",
        "app.focus",
        "desktop.open_app",
        "desktop.focus_app",
    ]
    mutating_tools = {"app.open", "app.focus", "desktop.open_app", "desktop.focus_app"}
    prompts = (
        "不能切到 Slack",
        "功能不能切到 Slack",
        "这个功能不能切到 Slack",
        "不要切到 Slack",
        "不要打开 Slack",
        "Cannot switch to Slack",
        "Can not switch to Slack",
        "Can't switch to Slack",
        "Can’t switch to Slack",
        "Do not switch to Slack",
        "Don’t switch to Slack",
        "Do not open Slack",
    )

    for prompt in prompts:
        decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
        direct_requests = planner_direct_tool_requests(prompt, allowed_tools)

        assert not mutating_tools.intersection(
            step.tool_name for step in decision.plan.tool_plan.steps
        ), prompt
        assert not mutating_tools.intersection(
            str(request.get("tool") or "") for request in direct_requests
        ), prompt


def test_purely_negated_click_and_type_never_plan_mutations() -> None:
    allowed_tools = [
        "desktop.list_apps",
        "desktop.running_apps",
        "desktop.ui_elements",
        "desktop.verify",
        "app.open",
        "app.focus",
        "desktop.open_app",
        "desktop.focus_app",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.safe_click",
        "desktop.safe_type_text",
        "desktop.click",
        "desktop.type",
        "desktop.type_text",
    ]
    mutating_tools = {
        "app.open",
        "app.focus",
        "desktop.open_app",
        "desktop.focus_app",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.safe_click",
        "desktop.safe_type_text",
        "desktop.click",
        "desktop.type",
        "desktop.type_text",
    }
    prompts = (
        "不要点击确定",
        "不要输入 hello",
        "不要在搜索框输入任何内容",
        "Do not click OK",
        "Don't click OK",
        "Cannot type hello",
        "Can not type hello",
        "Can't type hello",
        "Do not type hello",
        "Don't type hello",
    )

    for prompt in prompts:
        decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
        direct_requests = planner_direct_tool_requests(prompt, allowed_tools)

        assert not mutating_tools.intersection(
            step.tool_name for step in decision.plan.tool_plan.steps
        ), prompt
        assert not mutating_tools.intersection(
            str(request.get("tool") or "") for request in direct_requests
        ), prompt


def test_inability_statements_never_plan_app_mutations() -> None:
    allowed_tools = [
        "desktop.list_apps",
        "desktop.running_apps",
        "desktop.verify",
        "app.open",
        "app.focus",
        "desktop.open_app",
        "desktop.focus_app",
    ]
    mutating_tools = {"app.open", "app.focus", "desktop.open_app", "desktop.focus_app"}
    prompts = (
        "无法打开 Slack",
        "没法切到 Slack",
        "没有办法打开 Slack",
        "未能切到 Slack",
        "Could not open Slack",
        "Couldn't switch to Slack",
        "Won't open Slack",
        "Will not switch to Slack",
        "Shouldn't open Slack",
        "Mustn't switch to Slack",
    )

    for prompt in prompts:
        decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
        direct_requests = planner_direct_tool_requests(prompt, allowed_tools)

        assert not mutating_tools.intersection(
            step.tool_name for step in decision.plan.tool_plan.steps
        ), prompt
        assert not mutating_tools.intersection(
            str(request.get("tool") or "") for request in direct_requests
        ), prompt


def test_negated_focus_constraint_preserves_an_affirmative_click() -> None:
    allowed_tools = [
        "desktop.ui_elements",
        "desktop.click_ui_element",
        "desktop.verify",
        "app.open",
        "app.focus",
    ]
    mutating_app_tools = {"app.open", "app.focus"}

    for prompt in (
        "点击确定，不要切换焦点",
        "Click OK, do not switch focus",
    ):
        decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
        plan_tools = [step.tool_name for step in decision.plan.tool_plan.steps]
        direct_tools = [
            str(request.get("tool") or "")
            for request in planner_direct_tool_requests(prompt, allowed_tools)
        ]

        assert "desktop.click_ui_element" in plan_tools, prompt
        assert "desktop.click_ui_element" in direct_tools, prompt
        assert not mutating_app_tools.intersection(plan_tools), prompt
        assert not mutating_app_tools.intersection(direct_tools), prompt


def test_affirmative_action_after_negated_clause_is_still_planned() -> None:
    assert click_target_hint("不要点击取消，然后点击确定") == {
        "target": "确定",
        "role_filter": "",
        "click_count": 1,
    }
    assert type_into_ui_hint("不要在搜索框输入旧词，然后在搜索框输入新词") == {
        "target": "搜索框",
        "text": "新词",
        "role_filter": "text",
    }


def test_negated_click_clause_preserves_followup_click_in_runtime_plan() -> None:
    allowed_tools = [
        "desktop.running_apps",
        "desktop.ui_elements",
        "desktop.click_ui_element",
    ]
    prompts = (
        ("不要点击取消，点击确定", "确定"),
        ("不要点击取消但点击确定", "确定"),
        ("不要点击取消，而点击确定", "确定"),
        ("不要点击取消，然后点击确定", "确定"),
        ("Don't click Cancel, click OK", "OK"),
        ("Don't click Cancel, then click OK", "OK"),
    )

    for prompt, target in prompts:
        decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
        plan_clicks = [
            step
            for step in decision.plan.tool_plan.steps
            if step.tool_name == "desktop.click_ui_element"
        ]
        direct_clicks = [
            request
            for request in planner_direct_tool_requests(prompt, allowed_tools)
            if request.get("tool") == "desktop.click_ui_element"
        ]

        assert len(plan_clicks) == 1, prompt
        assert plan_clicks[0].input_preview.get("target") == target, prompt
        assert len(direct_clicks) == 1, prompt
        assert direct_clicks[0].get("input", {}).get("target") == target, prompt


def test_negated_open_clause_preserves_followup_app_target() -> None:
    allowed_tools = [
        "desktop.list_apps",
        "desktop.verify",
        "app.open",
        "app.focus",
    ]
    prompts = (
        "不要打开 Slack，打开 Calculator",
        "不要打开 Slack 但打开 Calculator",
        "不要打开 Slack，而打开 Calculator",
        "不要打开 Slack，然后打开 Calculator",
        "Do not open Slack, open Calculator",
        "Don't open Slack, then open Calculator",
    )
    expected_tools = ["desktop.list_apps", "app.open", "desktop.verify"]

    for prompt in prompts:
        decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
        direct_requests = planner_direct_tool_requests(prompt, allowed_tools)

        assert [step.tool_name for step in decision.plan.tool_plan.steps] == expected_tools, prompt
        assert decision.plan.tool_plan.steps[1].input_preview == {
            "app_name": "Calculator"
        }, prompt
        assert [request.get("tool") for request in direct_requests] == expected_tools, prompt
        assert direct_requests[1].get("input") == {"app_name": "Calculator"}, prompt


def test_soft_comma_action_boundary_does_not_split_negated_operands() -> None:
    for prompt in (
        "不要搜索苹果，橙子",
        "Do not search for apples, oranges",
        "不要发送消息“open Slack，open Calculator”",
        'Do not send the message "open Slack, open Calculator"',
    ):
        assert _speech_act_strip_unauthorized_contextual_tails(prompt) == "", prompt


def test_negated_type_clause_preserves_followup_field_and_text() -> None:
    allowed_tools = [
        "desktop.running_apps",
        "desktop.ui_elements",
        "desktop.type_into_ui_element",
        "desktop.safe_type_text",
    ]
    prompts = (
        ("不要在搜索框输入旧词，在搜索框输入新词", "新词"),
        ("不要在搜索框输入旧词但在搜索框输入新词", "新词"),
        ("不要在搜索框输入旧词，而在搜索框输入新词", "新词"),
        ("不要在搜索框输入旧词，然后在搜索框输入新词", "新词"),
        (
            "Don't type old into the search field, type new into the search field",
            "new",
        ),
        (
            "Don't type old into the search field, then type new into the search field",
            "new",
        ),
    )

    for prompt, text in prompts:
        decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
        plan_types = [
            step
            for step in decision.plan.tool_plan.steps
            if step.tool_name == "desktop.type_into_ui_element"
        ]
        direct_types = [
            request
            for request in planner_direct_tool_requests(prompt, allowed_tools)
            if request.get("tool") == "desktop.type_into_ui_element"
        ]

        assert len(plan_types) == 1, prompt
        assert plan_types[0].input_preview.get("target") in {"搜索框", "search field"}, prompt
        assert plan_types[0].input_preview.get("text") == text, prompt
        assert len(direct_types) == 1, prompt
        assert direct_types[0].get("input", {}).get("target") in {
            "搜索框",
            "search field",
        }, prompt
        assert direct_types[0].get("input", {}).get("text") == text, prompt


def test_background_open_with_explicit_negative_constraints_never_plans_interaction() -> None:
    allowed_tools = [
        "desktop.list_apps",
        "desktop.inspect_app",
        "desktop.ui_elements",
        "desktop.verify",
        "app.open",
        "app.focus",
        "app.focus_and_click_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
    ]

    for prompt in (
        "只在后台打开计算器，不要输入、点击或切换焦点。完成后简短回答。",
        (
            "Open Calculator in the background. Do not type, click, or switch focus. "
            "Reply briefly when done."
        ),
    ):
        requests = planner_direct_tool_requests(
            prompt,
            allowed_tools,
            metadata={"daily_desktop_intent": True},
        )

        assert [request["tool"] for request in requests] == [
            "desktop.list_apps",
            "app.open",
            "desktop.verify",
        ]
        assert requests[1]["input"] == {"app_name": "Calculator"}
        assert all(
            request["tool"]
            not in {
                "desktop.inspect_app",
                "desktop.ui_elements",
                "app.focus",
                "app.focus_and_click_ui_element",
                "app.focus_and_type_into_ui_element",
                "desktop.click_ui_element",
                "desktop.type_into_ui_element",
            }
        for request in requests
    )


def test_bilingual_background_open_and_explicit_focus_settings_remain_affirmative() -> None:
    allowed_tools = [
        "desktop.list_apps",
        "desktop.verify",
        "app.open",
        "app.focus",
        "system.settings_open",
    ]
    expected_open_tools = ["desktop.list_apps", "app.open", "desktop.verify"]
    prompts = (
        "只在后台打开计算器，不要输入、点击或切换焦点。完成后简短回答。",
        "Open Calculator in the background. Do not type, click, or switch focus. "
        "Reply briefly when done.",
    )

    for prompt in prompts:
        decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
        assert [step.tool_name for step in decision.plan.tool_plan.steps] == expected_open_tools
        assert [
            str(request.get("tool") or "")
            for request in planner_direct_tool_requests(prompt, allowed_tools)
        ] == expected_open_tools

    focus_settings = RuntimePlanner().decision(
        "Open Focus settings.",
        allowed_tools=allowed_tools,
    )
    assert [step.tool_name for step in focus_settings.plan.tool_plan.steps] == [
        "system.settings_open"
    ]
