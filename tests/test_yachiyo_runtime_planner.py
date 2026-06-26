"""Yachiyo capability-first runtime planner tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from apps.shell.yachiyo_agent import (
    PlannerDecisionSnapshot,
    RuntimePlanner,
    YachiyoAgentService,
)
from apps.shell.yachiyo_agent.planner_execution import planner_desktop_tool_requests


def _step_by_id(decision: PlannerDecisionSnapshot, step_id: str):
    return {step.step_id: step for step in decision.plan.tool_plan.steps}[step_id]


def _capability_by_id(decision: PlannerDecisionSnapshot, capability_id: str):
    return {capability.capability_id: capability for capability in decision.plan.capabilities}[capability_id]


def test_runtime_planner_routes_data_analysis_to_file_terminal_artifact_plan() -> None:
    decision = RuntimePlanner().decision(
        "请分析 sales.csv 并输出一份数据分析报告和图表",
        allowed_tools=["workspace.read", "workspace.list", "terminal.run", "artifact.write"],
    )

    assert decision.selected_intent.kind == "data_analysis"
    assert decision.selected_intent.inputs["data_source_hint"] == "sales.csv"
    assert decision.plan.route_to_studio is True
    assert decision.plan.tool_plan.missing_capabilities == []
    assert decision.plan.tool_plan.artifacts_expected == ["analysis-report.md"]
    step_ids = ["inspect-data-source", "run-analysis", "write-analysis-artifact"]
    assert [_step_by_id(decision, step_id).tool_name for step_id in step_ids] == [
        "workspace.read",
        "terminal.run",
        "artifact.write",
    ]
    assert _step_by_id(decision, "run-analysis").approval_required is True


def test_runtime_planner_marks_unavailable_steps_when_tools_are_disallowed() -> None:
    decision = RuntimePlanner().decision(
        "分析 sales.csv 并输出报告",
        allowed_tools=["workspace.read"],
    )

    assert decision.selected_intent.kind == "data_analysis"
    assert _step_by_id(decision, "inspect-data-source").status == "planned"
    assert _step_by_id(decision, "run-analysis").status == "unavailable"
    assert _step_by_id(decision, "write-analysis-artifact").status == "unavailable"
    assert set(decision.plan.tool_plan.missing_capabilities) == {
        "artifact.write",
        "terminal.execution",
    }


def test_runtime_planner_routes_unknown_desktop_app_without_known_alias() -> None:
    decision = RuntimePlanner().decision(
        "打开 SuperData Studio 并点击导入按钮",
        allowed_tools=[
            "desktop.running_apps",
            "app.open",
            "desktop.ui_elements",
            "desktop.click_ui_element",
        ],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "SuperData Studio"
    assert _step_by_id(decision, "discover-desktop-state").tool_name == "desktop.running_apps"
    assert _step_by_id(decision, "open-or-focus-app").input_preview == {
        "app_name": "SuperData Studio",
    }
    assert _step_by_id(decision, "operate-foreground-ui").tool_name == "desktop.click_ui_element"
    assert _step_by_id(decision, "operate-foreground-ui").approval_required is True


def test_runtime_planner_prefers_existing_app_foreground_combination_tools() -> None:
    decision = RuntimePlanner().decision(
        "打开 PixelForge 并点击导出按钮",
        allowed_tools=[
            "desktop.running_apps",
            "app.open_and_click_ui_element",
        ],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "operate-foreground-ui",
    ]
    operation = _step_by_id(decision, "operate-foreground-ui")
    assert operation.tool_name == "app.open_and_click_ui_element"
    assert operation.input_preview == {
        "app_name": "PixelForge",
        "target": "导出",
        "role_filter": "button",
        "click_count": 1,
        "limit": 80,
    }
    assert operation.depends_on == ["discover-desktop-state"]
    ui_capability = _capability_by_id(decision, "desktop.ui_operation")
    assert "app.open_and_click_ui_element" in ui_capability.tools


def test_planner_desktop_tool_requests_maps_arbitrary_app_click_plan() -> None:
    requests = planner_desktop_tool_requests(
        "打开 PixelForge 并点击导出按钮",
        allowed_tools=["app.open", "desktop.click_ui_element"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "PixelForge"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.click_ui_element",
            "input": {
                "target": "导出",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]


def test_planner_desktop_tool_requests_prefers_combined_app_foreground_tool() -> None:
    requests = planner_desktop_tool_requests(
        "打开 PixelForge 并点击导出按钮",
        allowed_tools=["app.open_and_click_ui_element", "app.open", "desktop.click_ui_element"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_click_ui_element",
            "input": {
                "app_name": "PixelForge",
                "target": "导出",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]


def test_planner_desktop_tool_requests_maps_arbitrary_app_typing_and_submit() -> None:
    requests = planner_desktop_tool_requests(
        "打开 PixelForge 搜索框输入 hello 并回车",
        allowed_tools=["app.open_and_type_into_ui_element", "desktop.submit_foreground"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_type_into_ui_element",
            "input": {
                "app_name": "PixelForge",
                "target": "搜索框",
                "text": "hello",
                "role_filter": "text",
                "limit": 80,
            },
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]


def test_yachiyo_agent_service_uses_fake_runtime_planner_port() -> None:
    class FakePlannerPort:
        def plan_chat_task(
            self,
            prompt: str,
            *,
            allowed_tools: Iterable[str] | None = None,
            metadata: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
            return RuntimePlanner().decision(
                prompt,
                allowed_tools=allowed_tools,
                metadata=metadata,
            ).model_dump(mode="json")

    decision = YachiyoAgentService(FakePlannerPort()).plan_chat_task(
        "打开 PixelForge 并点击导出",
        allowed_tools=["desktop.running_apps", "app.open", "desktop.click_ui_element"],
    )

    assert isinstance(decision, PlannerDecisionSnapshot)
    assert decision.selected_intent.kind == "desktop_operation"
    assert _step_by_id(decision, "open-or-focus-app").input_preview == {"app_name": "PixelForge"}
