"""Regression tests for browser search versus desktop discovery routing."""

from apps.shell.yachiyo_agent import RuntimePlanner
from apps.shell.yachiyo_agent.planner_execution import planner_tool_requests


ALLOWED_TOOLS = [
    "browser.open_url",
    "desktop.running_apps",
    "desktop.list_apps",
    "app.open",
]


def test_plain_chinese_web_search_outranks_generic_desktop_discovery() -> None:
    prompt = "搜一下 Yachiyo desktop agent"
    search_url = "https://www.google.com/search?q=Yachiyo+desktop+agent"
    metadata = {"runtime_planner_preflight_ui_before_action": True}

    decision = RuntimePlanner().decision(
        prompt,
        allowed_tools=ALLOWED_TOOLS,
        metadata=metadata,
    )

    assert decision.selected_intent.kind == "web_research"
    assert decision.selected_intent.inputs == {
        "url_hint": search_url,
        "browser_action": "open_search",
        "query": "Yachiyo desktop agent",
    }
    assert [step.tool_name for step in decision.plan.tool_plan.steps] == [
        "browser.open_url"
    ]
    assert planner_tool_requests(prompt, ALLOWED_TOOLS, metadata=metadata) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": search_url},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]


def test_explicit_running_app_discovery_remains_a_desktop_operation() -> None:
    decision = RuntimePlanner().decision(
        "列出当前运行的应用",
        allowed_tools=ALLOWED_TOOLS,
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert [step.tool_name for step in decision.plan.tool_plan.steps] == [
        "desktop.running_apps"
    ]


def test_local_looking_chinese_search_stays_on_desktop_tools() -> None:
    running_apps = RuntimePlanner().decision(
        "搜一下当前运行的应用",
        allowed_tools=ALLOWED_TOOLS,
    )
    settings = RuntimePlanner().decision(
        "搜一下系统设置",
        allowed_tools=ALLOWED_TOOLS,
    )

    assert running_apps.selected_intent.kind == "desktop_operation"
    assert [step.tool_name for step in running_apps.plan.tool_plan.steps] == [
        "desktop.running_apps"
    ]
    assert settings.selected_intent.kind == "desktop_operation"
    assert [step.tool_name for step in settings.plan.tool_plan.steps] == [
        "desktop.list_apps",
    ]


def test_generic_app_recommendation_searches_stay_on_the_web() -> None:
    for prompt in (
        "搜一下 best note taking app",
        "搜一下 calendar app",
        "搜索 项目管理软件",
    ):
        decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=ALLOWED_TOOLS,
        )

        assert decision.selected_intent.kind == "web_research"
        assert [step.tool_name for step in decision.plan.tool_plan.steps] == [
            "browser.open_url"
        ]
