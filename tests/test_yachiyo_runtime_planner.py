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
from apps.shell.yachiyo_agent.planner_execution import (
    planner_desktop_tool_requests,
    planner_tool_requests,
)


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
    assert decision.selected_intent.inputs["data_source_kind"] == "csv"
    assert decision.plan.route_to_studio is True
    assert decision.plan.tool_plan.missing_capabilities == []
    assert decision.plan.tool_plan.artifacts_expected == [
        "analysis-report.md",
        "analysis-chart.png",
    ]
    step_ids = ["inspect-data-source", "run-analysis", "write-analysis-artifact"]
    assert [_step_by_id(decision, step_id).tool_name for step_id in step_ids] == [
        "workspace.read",
        "terminal.run",
        "artifact.write",
    ]
    assert _step_by_id(decision, "run-analysis").approval_required is True
    assert _step_by_id(decision, "write-analysis-artifact").input_preview == {
        "paths": ["analysis-report.md", "analysis-chart.png"]
    }


def test_runtime_planner_prefers_builtin_data_analysis_for_simple_reports() -> None:
    decision = RuntimePlanner().decision(
        "请分析 sales.csv 并输出一份数据分析报告",
        allowed_tools=["data.analyze", "workspace.read", "artifact.write", "terminal.run"],
    )

    assert decision.selected_intent.kind == "data_analysis"
    assert decision.plan.tool_plan.required_capabilities == ["data.analysis"]
    assert decision.plan.tool_plan.missing_capabilities == []
    assert decision.plan.tool_plan.approvals_required == []
    assert decision.plan.tool_plan.artifacts_expected == ["analysis-report.md"]
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "analyze-data-file"
    ]
    step = _step_by_id(decision, "analyze-data-file")
    assert step.action == "analyze_data_file"
    assert step.tool_name == "data.analyze"
    assert step.input_preview == {
        "path": "sales.csv",
        "artifact_path": "analysis-report.md",
    }


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
    assert decision.selected_intent.inputs["data_source_hint"] == "sales.csv"
    assert decision.selected_intent.inputs["data_source_kind"] == "csv"
    assert _step_by_id(decision, "inspect-data-source").tool_name == "workspace.read"


def test_runtime_planner_predicts_data_analysis_artifacts_by_requested_outputs() -> None:
    decision = RuntimePlanner().decision(
        "分析 metrics.xlsx 并输出 html 报告、csv 汇总和图表",
        allowed_tools=["workspace.read", "terminal.run", "artifact.write"],
    )

    assert decision.selected_intent.kind == "data_analysis"
    assert decision.selected_intent.inputs["data_source_kind"] == "xlsx"
    assert decision.plan.tool_plan.artifacts_expected == [
        "analysis-report.md",
        "analysis-chart.png",
        "analysis-summary.csv",
        "analysis-report.html",
    ]
    assert _step_by_id(decision, "write-analysis-artifact").input_preview == {
        "paths": [
            "analysis-report.md",
            "analysis-chart.png",
            "analysis-summary.csv",
            "analysis-report.html",
        ]
    }


def test_runtime_planner_routes_file_organization_to_reviewable_plan() -> None:
    decision = RuntimePlanner().decision(
        "整理 Downloads 里的文件并按类型归档",
        allowed_tools=["workspace.list", "artifact.write", "terminal.run"],
    )

    assert decision.selected_intent.kind == "file_organization"
    assert decision.selected_intent.inputs == {
        "location_hint": "Downloads",
        "operation_hint": "archive",
    }
    assert decision.plan.route_to_studio is True
    assert decision.plan.tool_plan.artifacts_expected == ["file-organization-plan.md"]
    assert decision.plan.tool_plan.approvals_required == ["apply-file-organization"]
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "inspect-file-scope",
        "write-file-organization-plan",
        "apply-file-organization",
    ]
    assert _step_by_id(decision, "inspect-file-scope").tool_name == "workspace.list"
    assert _step_by_id(decision, "write-file-organization-plan").tool_name == "artifact.write"
    apply_step = _step_by_id(decision, "apply-file-organization")
    assert apply_step.tool_name == "terminal.run"
    assert apply_step.risk_level == "high"
    assert apply_step.approval_required is True


def test_runtime_planner_requires_file_location_for_file_organization() -> None:
    decision = RuntimePlanner().decision(
        "整理文件并删除重复项",
        allowed_tools=["workspace.list", "artifact.write"],
    )

    assert decision.selected_intent.kind == "file_organization"
    assert decision.selected_intent.missing_inputs == ["file_location"]
    assert decision.selected_intent.risk_level == "high"
    assert _step_by_id(decision, "apply-file-organization").status == "unavailable"


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
    assert _step_by_id(decision, "discover-desktop-state").action == "list_apps"
    assert _step_by_id(decision, "discover-desktop-state").tool_name == "desktop.running_apps"
    assert _step_by_id(decision, "open-or-focus-app").input_preview == {
        "app_name": "SuperData Studio",
    }
    assert _step_by_id(decision, "open-or-focus-app").action == "open_app"
    assert _step_by_id(decision, "operate-foreground-ui").tool_name == "desktop.click_ui_element"
    assert _step_by_id(decision, "operate-foreground-ui").action == "click"
    assert _step_by_id(decision, "operate-foreground-ui").approval_required is True
    assert _step_by_id(decision, "verify-desktop-result").tool_name == "desktop.ui_elements"
    assert _step_by_id(decision, "verify-desktop-result").action == "read_ui"
    assert _step_by_id(decision, "verify-desktop-result").depends_on == ["operate-foreground-ui"]


def test_runtime_planner_discovers_installed_apps_before_opening() -> None:
    decision = RuntimePlanner().decision(
        "打开 SuperData Studio",
        allowed_tools=["desktop.list_apps", "app.open", "desktop.active_window"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    discover = _step_by_id(decision, "discover-desktop-state")
    assert discover.tool_name == "desktop.list_apps"
    assert discover.action == "list_apps"
    assert discover.input_preview == {"query": "SuperData Studio", "limit": 20}
    assert "Discover installed apps" in discover.reason
    discovery_capability = _capability_by_id(decision, "desktop.app_discovery")
    assert "desktop.list_apps" in discovery_capability.tools
    assert "desktop.list_apps" in discovery_capability.available_tools
    assert _step_by_id(decision, "open-or-focus-app").depends_on == ["discover-desktop-state"]


def test_runtime_planner_routes_window_list_to_desktop_windows() -> None:
    decision = RuntimePlanner().decision(
        "显示微信窗口列表",
        allowed_tools=["desktop.list_apps", "desktop.windows"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "微信"
    assert decision.selected_intent.inputs["operation_hint"] == "list_windows"
    assert decision.selected_intent.inputs["window_list_hint"] == {"app_name": "微信"}
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "list-app-windows",
    ]
    discover = _step_by_id(decision, "discover-desktop-state")
    assert discover.tool_name == "desktop.list_apps"
    assert discover.input_preview == {"query": "微信", "limit": 20}
    list_windows = _step_by_id(decision, "list-app-windows")
    assert list_windows.tool_name == "desktop.windows"
    assert list_windows.action == "list_windows"
    assert list_windows.input_preview == {"app_name": "微信"}
    assert list_windows.depends_on == ["discover-desktop-state"]

    question_decision = RuntimePlanner().decision(
        "微信有哪些窗口",
        allowed_tools=["desktop.list_apps", "desktop.windows"],
    )
    assert question_decision.selected_intent.inputs["app_name_hint"] == "微信"
    assert _step_by_id(question_decision, "list-app-windows").input_preview == {
        "app_name": "微信",
    }


def test_runtime_planner_routes_focus_window_to_focus_window_tool() -> None:
    decision = RuntimePlanner().decision(
        "切到 Slack 的 general 窗口",
        allowed_tools=[
            "desktop.list_apps",
            "desktop.windows",
            "app.focus_window",
            "desktop.active_window",
        ],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "Slack"
    assert decision.selected_intent.inputs["operation_hint"] == "focus_window"
    assert decision.selected_intent.inputs["focus_window_hint"] == {
        "app_name": "Slack",
        "title_contains": "general",
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "list-app-windows",
        "focus-app-window",
        "verify-desktop-result",
    ]
    assert _step_by_id(decision, "discover-desktop-state").input_preview == {
        "query": "Slack",
        "limit": 20,
    }
    assert _step_by_id(decision, "list-app-windows").input_preview == {
        "app_name": "Slack",
    }
    focus = _step_by_id(decision, "focus-app-window")
    assert focus.tool_name == "app.focus_window"
    assert focus.action == "focus_window"
    assert focus.input_preview == {"app_name": "Slack", "title_contains": "general"}
    assert focus.depends_on == ["list-app-windows"]
    assert _step_by_id(decision, "verify-desktop-result").depends_on == ["focus-app-window"]


def test_runtime_planner_routes_current_ui_inspection_to_ui_elements() -> None:
    decision = RuntimePlanner().decision(
        "当前界面有哪些按钮",
        allowed_tools=["desktop.active_window", "desktop.ui_elements"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.risk_level == "low"
    assert decision.selected_intent.inputs["operation_hint"] == "read_ui"
    assert decision.selected_intent.inputs["ui_inspection_hint"] == {
        "role_filter": "button",
        "limit": 80,
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "read-foreground-ui",
    ]
    read_ui = _step_by_id(decision, "read-foreground-ui")
    assert read_ui.tool_name == "desktop.ui_elements"
    assert read_ui.action == "read_ui"
    assert read_ui.input_preview == {"role_filter": "button", "limit": 80}
    assert read_ui.depends_on == ["discover-desktop-state"]
    assert read_ui.approval_required is False


def test_runtime_planner_focuses_app_before_app_scoped_ui_inspection() -> None:
    decision = RuntimePlanner().decision(
        "Slack 有哪些按钮",
        allowed_tools=["desktop.list_apps", "app.focus", "desktop.ui_elements"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "Slack"
    assert decision.selected_intent.inputs["operation_hint"] == "read_ui"
    assert decision.selected_intent.inputs["ui_inspection_hint"] == {
        "role_filter": "button",
        "limit": 80,
        "app_name": "Slack",
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "open-or-focus-app",
        "read-foreground-ui",
    ]
    assert _step_by_id(decision, "discover-desktop-state").input_preview == {
        "query": "Slack",
        "limit": 20,
    }
    assert _step_by_id(decision, "open-or-focus-app").tool_name == "app.focus"
    read_ui = _step_by_id(decision, "read-foreground-ui")
    assert read_ui.tool_name == "desktop.ui_elements"
    assert read_ui.input_preview == {"role_filter": "button", "limit": 80}
    assert read_ui.depends_on == ["open-or-focus-app"]


def test_runtime_planner_routes_screen_capture_to_desktop_discovery() -> None:
    decision = RuntimePlanner().decision(
        "看一下当前屏幕",
        allowed_tools=["desktop.active_window", "screen.capture"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.risk_level == "low"
    assert decision.selected_intent.inputs["operation_hint"] == "capture_screen"
    assert decision.selected_intent.inputs["screen_capture_hint"] == {
        "reason": "user asked to capture the screen",
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "capture-screen",
    ]
    capture = _step_by_id(decision, "capture-screen")
    assert capture.tool_name == "screen.capture"
    assert capture.action == "capture_screen"
    assert capture.input_preview == {"reason": "user asked to capture the screen"}
    assert capture.depends_on == ["discover-desktop-state"]
    assert capture.approval_required is False


def test_runtime_planner_focuses_app_before_app_scoped_screen_capture() -> None:
    decision = RuntimePlanner().decision(
        "看一下 Slack 界面",
        allowed_tools=["desktop.list_apps", "app.focus", "screen.capture"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "Slack"
    assert decision.selected_intent.inputs["operation_hint"] == "capture_screen"
    assert decision.selected_intent.inputs["screen_capture_hint"] == {
        "reason": "user asked to capture the screen",
        "app_name": "Slack",
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "open-or-focus-app",
        "capture-screen",
    ]
    assert _step_by_id(decision, "open-or-focus-app").tool_name == "app.focus"
    assert _step_by_id(decision, "capture-screen").depends_on == ["open-or-focus-app"]


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
        "verify-desktop-result",
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
    assert _step_by_id(decision, "verify-desktop-result").status == "unavailable"
    ui_capability = _capability_by_id(decision, "desktop.ui_operation")
    assert "app.open_and_click_ui_element" in ui_capability.tools


def test_runtime_planner_verifies_desktop_open_result() -> None:
    decision = RuntimePlanner().decision(
        "打开 PixelForge",
        allowed_tools=["desktop.running_apps", "app.open", "desktop.active_window"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "open-or-focus-app",
        "verify-desktop-result",
    ]
    assert _step_by_id(decision, "verify-desktop-result").tool_name == "desktop.active_window"
    assert _step_by_id(decision, "verify-desktop-result").depends_on == ["open-or-focus-app"]


def test_runtime_planner_cleans_polite_app_name_suffixes() -> None:
    decision = RuntimePlanner().decision(
        "可以帮我打开 Word 吗",
        allowed_tools=["desktop.running_apps", "app.open", "desktop.active_window"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "Word"
    assert _step_by_id(decision, "open-or-focus-app").input_preview == {
        "app_name": "Word",
    }


def test_runtime_planner_models_explicit_submit_after_foreground_input() -> None:
    decision = RuntimePlanner().decision(
        "打开 PixelForge 搜索框输入 hello 并回车",
        allowed_tools=[
            "desktop.running_apps",
            "app.open_and_type_into_ui_element",
            "desktop.submit_foreground",
            "desktop.active_window",
        ],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "operate-foreground-ui",
        "submit-foreground-ui",
        "verify-desktop-result",
    ]
    submit = _step_by_id(decision, "submit-foreground-ui")
    assert submit.tool_name == "desktop.submit_foreground"
    assert submit.input_preview == {"action": "confirm"}
    assert submit.risk_level == "high"
    assert submit.approval_required is True
    assert submit.depends_on == ["operate-foreground-ui"]
    assert _step_by_id(decision, "verify-desktop-result").depends_on == [
        "submit-foreground-ui"
    ]


def test_runtime_planner_prefers_ui_readback_after_foreground_operation() -> None:
    decision = RuntimePlanner().decision(
        "打开 PixelForge 搜索框输入 hello 并回车",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_type_into_ui_element",
            "desktop.submit_foreground",
            "desktop.ui_elements",
            "desktop.active_window",
        ],
    )

    verify = _step_by_id(decision, "verify-desktop-result")
    assert verify.tool_name == "desktop.ui_elements"
    assert verify.action == "read_ui"
    assert verify.input_preview == {"role_filter": "text", "limit": 80}
    assert verify.depends_on == ["submit-foreground-ui"]
    assert "Read foreground UI" in verify.reason


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


def test_runtime_planner_routes_system_volume_to_system_control() -> None:
    decision = RuntimePlanner().decision(
        "把系统音量调到 50%",
        allowed_tools=["system.volume"],
    )

    assert decision.selected_intent.kind == "system_control"
    assert decision.selected_intent.inputs == {
        "kind": "volume",
        "payload": {"action": "set", "level": 50},
    }
    step = _step_by_id(decision, "control-system-state")
    assert step.capability_id == "system.control"
    assert step.tool_name == "system.volume"
    assert step.input_preview == {"action": "set", "level": 50}


def test_runtime_planner_routes_brightness_and_display_controls() -> None:
    brightness = RuntimePlanner().decision(
        "屏幕太亮了，调暗一点",
        allowed_tools=["system.brightness"],
    )
    display_sleep = RuntimePlanner().decision(
        "关闭屏幕",
        allowed_tools=["system.display_sleep"],
    )

    assert brightness.selected_intent.kind == "system_control"
    assert _step_by_id(brightness, "control-system-state").tool_name == "system.brightness"
    assert _step_by_id(brightness, "control-system-state").input_preview == {
        "action": "down",
        "step": 2,
    }
    assert display_sleep.selected_intent.kind == "system_control"
    assert _step_by_id(display_sleep, "control-system-state").tool_name == "system.display_sleep"


def test_runtime_planner_routes_communication_to_compose_capability() -> None:
    decision = RuntimePlanner().decision(
        "发送消息给 Alice：今晚八点见",
        allowed_tools=["desktop.active_window", "desktop.type_into_ui_element", "artifact.write"],
    )

    assert decision.selected_intent.kind == "communication"
    assert decision.plan.route_to_studio is True
    assert decision.plan.tool_plan.missing_capabilities == []
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-communication-surface",
        "draft-communication",
    ]
    assert _step_by_id(decision, "discover-communication-surface").tool_name == "desktop.active_window"
    draft_step = _step_by_id(decision, "draft-communication")
    assert draft_step.capability_id == "communication.compose"
    assert draft_step.tool_name == "desktop.type_into_ui_element"
    assert draft_step.approval_required is True
    communication_capability = _capability_by_id(decision, "communication.compose")
    assert "desktop.type_into_ui_element" in communication_capability.available_tools


def test_runtime_planner_can_fall_back_to_artifact_for_communication_draft() -> None:
    decision = RuntimePlanner().decision(
        "写一封邮件给 Alice 说明项目进展",
        allowed_tools=["artifact.write"],
    )

    assert decision.selected_intent.kind == "communication"
    assert decision.plan.tool_plan.missing_capabilities == []
    draft_step = _step_by_id(decision, "draft-communication")
    assert draft_step.tool_name == "artifact.write"
    assert draft_step.depends_on == []
    assert draft_step.approval_required is True


def test_runtime_planner_routes_clipboard_write_to_clipboard_capability() -> None:
    decision = RuntimePlanner().decision(
        "把 hello 复制到剪贴板",
        allowed_tools=["clipboard.write"],
    )

    assert decision.selected_intent.kind == "clipboard_operation"
    assert decision.selected_intent.inputs == {"action": "write", "text": "hello"}
    assert decision.plan.tool_plan.missing_capabilities == []
    step = _step_by_id(decision, "write-clipboard")
    assert step.capability_id == "clipboard.read_write"
    assert step.tool_name == "clipboard.write"
    assert step.input_preview == {"text": "hello"}


def test_runtime_planner_routes_clipboard_read_to_clipboard_capability() -> None:
    decision = RuntimePlanner().decision(
        "读取剪贴板内容",
        allowed_tools=["clipboard.read"],
    )

    assert decision.selected_intent.kind == "clipboard_operation"
    step = _step_by_id(decision, "read-clipboard")
    assert step.tool_name == "clipboard.read"
    clipboard_capability = _capability_by_id(decision, "clipboard.read_write")
    assert "clipboard.read" in clipboard_capability.available_tools


def test_runtime_planner_routes_selected_text_read_through_clipboard() -> None:
    decision = RuntimePlanner().decision(
        "读一下选中的内容",
        allowed_tools=["desktop.safe_shortcut", "clipboard.read"],
    )

    assert decision.selected_intent.kind == "clipboard_operation"
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "copy-selected-text",
        "read-clipboard",
    ]
    assert _step_by_id(decision, "copy-selected-text").input_preview == {"action": "copy"}
    assert _step_by_id(decision, "read-clipboard").depends_on == ["copy-selected-text"]


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


def test_runtime_planner_routes_explicit_reminder_to_schedule_capability() -> None:
    decision = RuntimePlanner().decision(
        "创建提醒事项：买牛奶",
        allowed_tools=["reminders.create"],
    )

    assert decision.selected_intent.kind == "schedule"
    step = _step_by_id(decision, "create-schedule-item")
    assert step.tool_name == "reminders.create"
    assert step.input_preview == {"title": "买牛奶"}
    assert step.approval_required is True


def test_runtime_planner_routes_iso_calendar_event_to_schedule_capability() -> None:
    decision = RuntimePlanner().decision(
        "创建日历事件：项目会 2026-06-27T15:00",
        allowed_tools=["calendar.create_event"],
    )

    assert decision.selected_intent.kind == "schedule"
    step = _step_by_id(decision, "create-schedule-item")
    assert step.tool_name == "calendar.create_event"
    assert step.input_preview == {
        "title": "项目会",
        "start_at": "2026-06-27T15:00",
    }


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


def test_planner_desktop_tool_requests_preserves_discover_operate_verify_steps() -> None:
    requests = planner_desktop_tool_requests(
        "打开 PixelForge 并点击导出按钮",
        allowed_tools=[
            "desktop.running_apps",
            "app.open",
            "desktop.click_ui_element",
            "desktop.ui_elements",
        ],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.running_apps",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
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
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "button", "limit": 80},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]


def test_planner_desktop_tool_requests_uses_list_apps_when_available() -> None:
    requests = planner_desktop_tool_requests(
        "打开 PixelForge 并点击导出按钮",
        allowed_tools=[
            "desktop.list_apps",
            "app.open",
            "desktop.click_ui_element",
            "desktop.ui_elements",
        ],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "PixelForge", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
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
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "button", "limit": 80},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]


def test_planner_desktop_tool_requests_discovers_app_name_from_in_app_phrase() -> None:
    decision = RuntimePlanner().decision(
        "在 PixelForge 里点击导出按钮",
        allowed_tools=["app.open_and_click_ui_element", "desktop.active_window"],
    )
    requests = planner_desktop_tool_requests(
        "click Export in PixelForge",
        allowed_tools=["app.open_and_click_ui_element"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "PixelForge"
    assert _step_by_id(decision, "operate-foreground-ui").tool_name == "app.open_and_click_ui_element"
    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_click_ui_element",
            "input": {
                "app_name": "PixelForge",
                "target": "Export",
                "role_filter": "",
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


def test_planner_desktop_tool_requests_maps_focus_window_sequence() -> None:
    requests = planner_desktop_tool_requests(
        "切到 Slack 的 general 窗口",
        allowed_tools=[
            "desktop.list_apps",
            "desktop.windows",
            "app.focus_window",
            "desktop.active_window",
        ],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "Slack", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.windows",
            "input": {"app_name": "Slack"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "app.focus_window",
            "input": {"app_name": "Slack", "title_contains": "general"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]


def test_planner_desktop_tool_requests_maps_app_scoped_ui_inspection() -> None:
    requests = planner_desktop_tool_requests(
        "Slack 有哪些按钮",
        allowed_tools=["desktop.list_apps", "app.focus", "desktop.ui_elements"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "Slack", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Slack"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "button", "limit": 80},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]


def test_planner_desktop_tool_requests_maps_app_scoped_screen_capture() -> None:
    requests = planner_desktop_tool_requests(
        "看一下 Slack 界面",
        allowed_tools=["desktop.list_apps", "app.focus", "screen.capture"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "Slack", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Slack"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
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


def test_planner_tool_requests_maps_system_control_plan() -> None:
    requests = planner_tool_requests(
        "打开屏保",
        allowed_tools=["system.screen_saver_start"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "system.screen_saver_start",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_system_control",
        }
    ]


def test_planner_tool_requests_prefetches_text_data_source_for_analysis() -> None:
    requests = planner_tool_requests(
        "请分析 data/sales.csv 并输出报告",
        allowed_tools=["workspace.read", "terminal.run", "artifact.write"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "workspace.read",
            "input": {"path": "data/sales.csv"},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_data_source",
            "continue_to_model": True,
        }
    ]


def test_planner_tool_requests_uses_builtin_data_analysis_when_available() -> None:
    requests = planner_tool_requests(
        "请分析 data/sales.csv 并输出报告",
        allowed_tools=["data.analyze", "workspace.read", "terminal.run", "artifact.write"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "data.analyze",
            "input": {
                "path": "data/sales.csv",
                "artifact_path": "analysis-report.md",
            },
            "source": "runtime_planner",
            "planning_reason": "planner_builtin_data_analysis",
        }
    ]


def test_planner_tool_requests_does_not_prefetch_binary_or_external_data_sources() -> None:
    assert (
        planner_tool_requests(
            "请分析 /tmp/sales.csv",
            allowed_tools=["workspace.read", "terminal.run", "artifact.write"],
        )
        == []
    )
    assert (
        planner_tool_requests(
            "请分析 report.xlsx",
            allowed_tools=["workspace.read", "terminal.run", "artifact.write"],
        )
        == []
    )


def test_planner_tool_requests_maps_explicit_hotkey_plan() -> None:
    requests = planner_tool_requests(
        "Can you press Command L?",
        allowed_tools=["desktop.hotkey", "desktop.click_ui_element"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "l", "modifiers": ["command"]},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_hotkey",
        }
    ]


def test_planner_tool_requests_maps_app_hotkey_plan() -> None:
    requests = planner_tool_requests(
        "open Chrome and press command l",
        allowed_tools=["app.open_and_hotkey", "app.open_and_click_ui_element"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_hotkey",
            "input": {"app_name": "Chrome", "key": "l", "modifiers": ["command"]},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_hotkey",
        }
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


def test_planner_tool_requests_maps_explicit_reminder_plan() -> None:
    requests = planner_tool_requests(
        "创建提醒事项：买牛奶",
        allowed_tools=["reminders.create"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "买牛奶"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_schedule",
        }
    ]


def test_planner_tool_requests_maps_explicit_clipboard_write_plan() -> None:
    requests = planner_tool_requests(
        "把 hello 复制到剪贴板",
        allowed_tools=["clipboard.write"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "clipboard.write",
            "input": {"text": "hello"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_clipboard",
        }
    ]


def test_planner_tool_requests_maps_selected_text_read_plan() -> None:
    requests = planner_tool_requests(
        "读一下选中的内容",
        allowed_tools=["desktop.safe_shortcut", "clipboard.read"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_clipboard",
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_clipboard",
        },
    ]


def test_planner_desktop_tool_requests_remains_compat_wrapper() -> None:
    assert planner_desktop_tool_requests(
        "打开 https://example.com",
        allowed_tools=["browser.open_url"],
    ) == planner_tool_requests(
        "打开 https://example.com",
        allowed_tools=["browser.open_url"],
    )


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
