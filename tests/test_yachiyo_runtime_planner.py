"""Yachiyo capability-first runtime planner tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from apps.shell.yachiyo_agent import (
    PlannerDecisionSnapshot,
    RuntimePlanner,
    YachiyoAgentService,
    capability_snapshots,
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


def test_runtime_planner_timeline_preview_includes_created_plan_event() -> None:
    decision = RuntimePlanner().decision(
        "请分析 sales.csv 并输出一份数据分析报告",
        allowed_tools=["workspace.read", "terminal.run", "artifact.write"],
    )

    event_types = [event["event_type"] for event in decision.plan.timeline_preview]
    assert event_types == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.plan.step",
        "agent.plan.step",
        "agent.plan.step",
    ]
    created = decision.plan.timeline_preview[1]
    assert created["payload"]["plan_id"] == decision.plan.plan_id
    assert created["payload"]["tool_plan_id"] == decision.plan.tool_plan.plan_id
    assert created["payload"]["approvals_required"] == ["run-analysis"]
    assert created["payload"]["artifacts_expected"] == ["analysis-report.md"]
    assert created["payload"]["route_to_studio"] is True


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


def test_runtime_planner_treats_app_names_as_data_analysis_tool_hints() -> None:
    decision = RuntimePlanner().decision(
        "打开 Excel 分析 sales.csv 并输出报告",
        allowed_tools=["workspace.read", "terminal.run", "artifact.write", "app.open"],
    )

    assert decision.selected_intent.kind == "data_analysis"
    assert decision.selected_intent.inputs["data_source_hint"] == "sales.csv"
    assert _step_by_id(decision, "run-analysis").tool_name == "terminal.run"


def test_runtime_planner_uses_file_metadata_for_generic_analysis_requests() -> None:
    decision = RuntimePlanner().decision(
        "分析一下这个文件",
        allowed_tools=["workspace.read", "terminal.run", "artifact.write"],
        metadata={"file": "sales.csv"},
    )

    assert decision.selected_intent.kind == "data_analysis"
    assert decision.selected_intent.missing_inputs == []
    assert _step_by_id(decision, "inspect-data-source").tool_name == "workspace.read"


def test_runtime_planner_prefers_research_deliverable_over_browser_app_hint() -> None:
    decision = RuntimePlanner().decision(
        "打开浏览器调研 OpenAI 最新新闻并总结报告",
        allowed_tools=["browser.current_page", "browser.extract_text", "artifact.write", "app.open"],
    )

    assert decision.selected_intent.kind == "web_research"
    assert _step_by_id(decision, "open-or-read-web").tool_name == "browser.current_page"


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


def test_runtime_planner_routes_media_playback_to_media_capability() -> None:
    decision = RuntimePlanner().decision(
        "能否帮我播放 Apple Music?",
        allowed_tools=["media.apple_music_open_and_play"],
    )

    assert decision.selected_intent.kind == "media_playback"
    assert decision.selected_intent.inputs == {
        "action": "play",
        "app_name": "Music",
        "query": "",
    }
    step = _step_by_id(decision, "control-media-playback")
    assert step.tool_name == "media.apple_music_open_and_play"
    assert step.input_preview == {}
    media_capability = _capability_by_id(decision, "media.playback")
    assert "media.apple_music_open_and_play" in media_capability.tools


def test_runtime_planner_routes_media_query_to_apple_music_search_play() -> None:
    decision = RuntimePlanner().decision(
        "播放超时空辉夜姬",
        allowed_tools=["media.apple_music_play"],
    )

    assert decision.selected_intent.kind == "media_playback"
    assert decision.selected_intent.inputs["query"] == "超时空辉夜姬"
    step = _step_by_id(decision, "control-media-playback")
    assert step.tool_name == "media.apple_music_play"
    assert step.input_preview == {"query": "超时空辉夜姬"}


def test_capability_registry_discovers_browser_namespace_tools_from_policy() -> None:
    snapshots = capability_snapshots(
        allowed_tools=["browser.print_page"],
        capability_ids=["browser.research"],
    )

    assert len(snapshots) == 1
    assert "browser.print_page" in snapshots[0].tools
    assert "browser.print_page" in snapshots[0].available_tools


def test_capability_registry_does_not_treat_workspace_patch_as_read() -> None:
    snapshots = capability_snapshots(
        allowed_tools=["workspace.write_patch"],
        capability_ids=["file.workspace_read"],
    )

    assert len(snapshots) == 1
    assert "workspace.write_patch" not in snapshots[0].tools
    assert snapshots[0].available_tools == []


def test_runtime_planner_uses_browser_screenshot_tool_from_catalog() -> None:
    decision = RuntimePlanner().decision(
        "请调研 https://example.com 并截图",
        allowed_tools=["browser.open_url_and_screenshot", "artifact.write"],
    )

    assert decision.selected_intent.kind == "web_research"
    assert decision.plan.tool_plan.missing_capabilities == []
    assert _step_by_id(decision, "open-or-read-web").tool_name == "browser.open_url_and_screenshot"
    browser_capability = _capability_by_id(decision, "browser.research")
    assert "browser.open_url_and_screenshot" in browser_capability.available_tools


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


def test_planner_desktop_tool_requests_maps_media_playback_plan() -> None:
    requests = planner_desktop_tool_requests(
        "播放 Spotify",
        allowed_tools=["media.music_app_open_and_play"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "media.music_app_open_and_play",
            "input": {"app_name": "Spotify"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_media_playback",
        },
    ]


def test_planner_tool_requests_maps_explicit_browser_url_plan() -> None:
    requests = planner_desktop_tool_requests(
        "打开 https://example.com",
        allowed_tools=["browser.open_url"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://example.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]


def test_planner_tool_requests_keeps_research_deliverables_in_model_loop() -> None:
    requests = planner_desktop_tool_requests(
        "调研 https://example.com 并总结报告",
        allowed_tools=["browser.open_url_and_extract_text"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url_and_extract_text",
            "input": {"url": "https://example.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
            "continue_to_model": True,
        }
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
