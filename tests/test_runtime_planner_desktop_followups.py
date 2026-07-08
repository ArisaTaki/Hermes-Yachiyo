"""Focused desktop follow-up planning coverage."""

from __future__ import annotations

from apps.shell.yachiyo_agent.desktop_plan_hints import (
    click_target_hint,
    safe_type_text_hint,
)
from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner


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
