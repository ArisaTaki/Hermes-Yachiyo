"""Yachiyo capability-first runtime planner tests."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from apps.shell.yachiyo_agent import (
    PlannerDecisionSnapshot,
    RuntimePlanner,
    YachiyoAgentService,
    capability_snapshots,
)
from apps.shell.yachiyo_agent.planner_execution import (
    planner_direct_tool_requests,
    planner_desktop_tool_requests,
    planner_tool_requests,
)
from apps.shell.yachiyo_agent.entrypoint_tool_selection import (
    planner_first_direct_decision_and_tool_requests,
    planner_first_direct_tool_selection,
)
from apps.shell.yachiyo_agent.planner_projection import (
    planner_selection_payload,
    planner_selection_timeline_event,
    planner_timeline_events,
)


def _step_by_id(decision: PlannerDecisionSnapshot, step_id: str):
    return {step.step_id: step for step in decision.plan.tool_plan.steps}[step_id]


def _capability_by_id(decision: PlannerDecisionSnapshot, capability_id: str):
    return {capability.capability_id: capability for capability in decision.plan.capabilities}[capability_id]


def _recording_legacy_requests(
    calls: list[dict[str, Any]],
) -> Callable[[str, list[str]], list[dict[str, Any]]]:
    def record(prompt: str, allowed_tools: list[str]) -> list[dict[str, Any]]:
        calls.append({"prompt": prompt, "allowed_tools": list(allowed_tools)})
        return []

    return record


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


def test_runtime_planner_uses_builtin_data_analysis_for_standard_artifacts() -> None:
    decision = RuntimePlanner().decision(
        "分析 metrics.xlsx 并输出 html 报告、csv 汇总和图表",
        allowed_tools=["data.analyze", "workspace.read", "terminal.run", "artifact.write"],
    )

    assert decision.selected_intent.kind == "data_analysis"
    assert decision.selected_intent.inputs["data_source_kind"] == "xlsx"
    assert decision.plan.tool_plan.approvals_required == []
    assert decision.plan.tool_plan.artifacts_expected == [
        "analysis-report.md",
        "analysis-chart.png",
        "analysis-summary.csv",
        "analysis-report.html",
    ]
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "analyze-data-file"
    ]
    step = _step_by_id(decision, "analyze-data-file")
    assert step.tool_name == "data.analyze"
    assert step.input_preview == {
        "path": "metrics.xlsx",
        "artifact_path": "analysis-report.md",
        "artifact_paths": [
            "analysis-report.md",
            "analysis-chart.png",
            "analysis-summary.csv",
            "analysis-report.html",
        ],
    }


def test_runtime_planner_prefers_builtin_data_analysis_for_markdown_tables() -> None:
    decision = RuntimePlanner().decision(
        "请分析 data/sales.md 里的表格并输出报告",
        allowed_tools=["data.analyze", "workspace.read", "terminal.run", "artifact.write"],
    )

    assert decision.selected_intent.kind == "data_analysis"
    assert decision.selected_intent.inputs["data_source_hint"] == "data/sales.md"
    assert decision.selected_intent.inputs["data_source_kind"] == "text_table"
    assert decision.plan.tool_plan.approvals_required == []
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "analyze-data-file"
    ]
    step = _step_by_id(decision, "analyze-data-file")
    assert step.tool_name == "data.analyze"
    assert step.input_preview == {
        "path": "data/sales.md",
        "artifact_path": "analysis-report.md",
    }


def test_runtime_planner_prefers_builtin_data_analysis_for_jsonl() -> None:
    decision = RuntimePlanner().decision(
        "请分析 logs/events.jsonl 并输出报告",
        allowed_tools=["data.analyze", "workspace.read", "terminal.run", "artifact.write"],
    )

    assert decision.selected_intent.kind == "data_analysis"
    assert decision.selected_intent.inputs["data_source_hint"] == "logs/events.jsonl"
    assert decision.selected_intent.inputs["data_source_kind"] == "jsonl"
    assert decision.plan.tool_plan.approvals_required == []
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "analyze-data-file"
    ]
    step = _step_by_id(decision, "analyze-data-file")
    assert step.tool_name == "data.analyze"
    assert step.input_preview == {
        "path": "logs/events.jsonl",
        "artifact_path": "analysis-report.md",
    }


def test_runtime_planner_prefetches_selected_data_for_analysis() -> None:
    decision = RuntimePlanner().decision(
        "分析当前选中的数据并生成报告",
        allowed_tools=["desktop.safe_shortcut", "clipboard.read", "terminal.run", "artifact.write"],
    )

    assert decision.selected_intent.kind == "data_analysis"
    assert decision.selected_intent.inputs["context_source"] == "selection"
    assert decision.selected_intent.missing_inputs == []
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "copy-selected-data-context",
        "read-data-context",
        "run-analysis",
        "write-analysis-artifact",
    ]
    assert _step_by_id(decision, "run-analysis").approval_required is True
    assert _step_by_id(decision, "write-analysis-artifact").input_preview == {
        "paths": ["analysis-report.md"],
        "body_source": "selection",
    }


def test_runtime_planner_keeps_parquet_on_approved_python_path() -> None:
    decision = RuntimePlanner().decision(
        "请分析 metrics.parquet 并输出报告",
        allowed_tools=["data.analyze", "workspace.read", "terminal.run", "artifact.write"],
    )

    assert decision.selected_intent.kind == "data_analysis"
    assert decision.selected_intent.inputs["data_source_kind"] == "parquet"
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "inspect-data-source",
        "run-analysis",
        "write-analysis-artifact",
    ]
    assert _step_by_id(decision, "run-analysis").tool_name == "terminal.run"
    assert _step_by_id(decision, "run-analysis").approval_required is True


def test_runtime_planner_keeps_legacy_xls_on_approved_python_path() -> None:
    decision = RuntimePlanner().decision(
        "请分析 legacy-report.xls 并输出报告",
        allowed_tools=["data.analyze", "workspace.read", "terminal.run", "artifact.write"],
    )

    assert decision.selected_intent.kind == "data_analysis"
    assert decision.selected_intent.inputs["data_source_kind"] == "xls"
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "inspect-data-source",
        "run-analysis",
        "write-analysis-artifact",
    ]
    assert _step_by_id(decision, "run-analysis").tool_name == "terminal.run"
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


def test_runtime_planner_timeline_events_include_full_studio_trace_payloads() -> None:
    decision = RuntimePlanner().decision(
        "打开 PixelForge 并点击导出按钮",
        allowed_tools=["app.open", "desktop.click_ui_element"],
    )

    events = planner_timeline_events(decision)

    assert [event["event"] for event in events[:3]] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.plan.step",
    ]
    assert events[0]["payload"]["intent"]["kind"] == "desktop_operation"
    plan_tools = [
        step["tool_name"]
        for step in events[1]["payload"]["plan"]["tool_plan"]["steps"]
        if step.get("tool_name")
    ]
    assert plan_tools == ["app.open", "desktop.click_ui_element"]
    assert events[2]["payload"]["step"]["step_id"] == "discover-desktop-state"


def test_runtime_planner_selection_projection_uses_shared_replay_shape() -> None:
    decision = RuntimePlanner().decision(
        "打开 PixelForge",
        allowed_tools=["desktop.list_apps", "app.open", "desktop.active_window"],
    )
    planner_requests = [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "PixelForge"},
        }
    ]

    payload = planner_selection_payload(
        decision=decision,
        planner_requests=planner_requests,
        legacy_requests=[],
        selected_requests=planner_requests,
        selected_source="runtime_planner",
        selected_reason="runtime_planner_direct",
    )
    event = planner_selection_timeline_event(payload)

    assert payload["source"] == "runtime_planner"
    assert payload["selection_source"] == "runtime_planner"
    assert payload["selection_reason"] == "runtime_planner_direct"
    assert payload["plan_tools"] == ["desktop.list_apps", "app.open", "desktop.active_window"]
    assert payload["plan_capabilities"] == [
        "desktop.app_discovery",
        "desktop.app_control",
        "desktop.ui_operation",
    ]
    assert payload["required_capabilities"] == ["desktop.app_discovery"]
    assert payload["missing_capabilities"] == []
    assert payload["planner_tools"] == ["app.open"]
    assert payload["legacy_tools"] == []
    assert payload["selected_tools"] == ["app.open"]
    assert payload["plan_step_count"] == 3
    assert payload["plan_capability_count"] == 3
    assert payload["missing_capability_count"] == 0
    assert payload["planner_request_count"] == 1
    assert payload["legacy_request_count"] == 0
    assert payload["selected_request_count"] == 1
    assert payload["decision_id"] == decision.decision_id
    assert payload["plan_id"] == decision.plan.plan_id
    assert payload["intent_kind"] == "desktop_operation"
    assert event["event"] == "agent.plan.selection"
    assert event["detail"] == "runtime_planner"
    assert event["payload"] == payload


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


def test_runtime_planner_discovers_data_source_scope_for_analysis() -> None:
    scoped_decision = RuntimePlanner().decision(
        "分析 Downloads 里的销售数据并输出报告",
        allowed_tools=["workspace.list", "workspace.read", "terminal.run", "artifact.write"],
    )
    generic_decision = RuntimePlanner().decision(
        "分析数据并输出报告",
        allowed_tools=["workspace.list", "workspace.read", "terminal.run", "artifact.write"],
    )

    assert scoped_decision.selected_intent.kind == "data_analysis"
    assert scoped_decision.selected_intent.inputs["data_source_scope_hint"] == "Downloads"
    assert scoped_decision.selected_intent.missing_inputs == []
    assert _step_by_id(scoped_decision, "inspect-data-source").tool_name == "workspace.list"
    assert _step_by_id(scoped_decision, "inspect-data-source").input_preview == {
        "path": "Downloads"
    }
    assert generic_decision.selected_intent.kind == "data_analysis"
    assert generic_decision.selected_intent.missing_inputs == []
    assert _step_by_id(generic_decision, "inspect-data-source").tool_name == "workspace.list"
    assert _step_by_id(generic_decision, "inspect-data-source").input_preview == {}


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

    organize_decision = RuntimePlanner().decision(
        "整理 Downloads 里的文件",
        allowed_tools=["workspace.list", "artifact.write", "terminal.run"],
    )
    assert organize_decision.selected_intent.kind == "file_organization"
    assert organize_decision.selected_intent.inputs == {
        "location_hint": "Downloads",
        "operation_hint": "organize",
    }
    assert _step_by_id(organize_decision, "apply-file-organization").approval_required is True


def test_runtime_planner_preserves_workflow_and_multi_agent_orchestration_routes() -> None:
    workflow = RuntimePlanner().decision(
        "创建一个 workflow 分析数据然后发微信给我",
        allowed_tools=["workflow.run", "workspace.read", "terminal.run", "artifact.write"],
    )

    assert workflow.selected_intent.kind == "workflow_orchestration"
    assert workflow.plan.route_to_studio is True
    workflow_step = _step_by_id(workflow, "workflow-orchestration")
    assert workflow_step.capability_id == "workflow.orchestration"
    assert workflow_step.action == "start_workflow"
    assert workflow_step.status == "planned"

    workflow_with_data_words = RuntimePlanner().decision(
        "启动工作流分析 sales.csv",
        allowed_tools=["workflow.run", "data.analyze", "workspace.read"],
    )
    assert workflow_with_data_words.selected_intent.kind == "workflow_orchestration"

    group = RuntimePlanner().decision(
        "让两个 agent 分别调研 Hanako 和 Hermes 然后汇总",
        allowed_tools=["group.run", "browser.open_url_and_extract_text", "artifact.write"],
    )

    assert group.selected_intent.kind == "multi_agent"
    assert group.plan.route_to_studio is True
    group_step = _step_by_id(group, "group-multi_agent")
    assert group_step.capability_id == "group.multi_agent"
    assert group_step.action == "start_group_run"
    assert group_step.status == "planned"

    single_agent_research = RuntimePlanner().decision(
        "研究 agent runtime 并总结",
        allowed_tools=["browser.open_url", "artifact.write"],
    )
    assert single_agent_research.selected_intent.kind == "web_research"


def test_runtime_planner_routes_explicit_terminal_command_to_approval_plan() -> None:
    decision = RuntimePlanner().decision(
        "打开终端运行 ls",
        allowed_tools=["app.open", "desktop.list_apps", "terminal.run"],
    )

    assert decision.selected_intent.kind == "code_task"
    assert decision.selected_intent.title == "Terminal Command"
    assert decision.selected_intent.inputs == {
        "terminal_command_hint": {"command": "ls"}
    }
    assert decision.plan.route_to_studio is True
    assert decision.plan.tool_plan.required_capabilities == ["terminal.execution"]
    assert decision.plan.tool_plan.approvals_required == ["run-terminal-command"]
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "run-terminal-command"
    ]
    step = _step_by_id(decision, "run-terminal-command")
    assert step.tool_name == "terminal.run"
    assert step.input_preview == {"command": "ls"}
    assert step.approval_required is True
    assert planner_direct_tool_requests(
        "run npm test in terminal",
        ["terminal.run"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "terminal.run",
            "input": {"command": "npm test"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_terminal_command",
        }
    ]


def test_runtime_planner_routes_local_file_access_to_desktop_file_tools() -> None:
    open_decision = RuntimePlanner().decision(
        "打开当前选中的 Finder 文件",
        allowed_tools=["desktop.open_path", "desktop.reveal_path"],
    )

    assert open_decision.selected_intent.kind == "file_access"
    assert open_decision.selected_intent.inputs == {
        "action": "open_path",
        "path": "finder_selection",
    }
    open_step = _step_by_id(open_decision, "open-local-path")
    assert open_step.capability_id == "file.desktop_access"
    assert open_step.tool_name == "desktop.open_path"
    assert open_step.action == "open_path"
    assert open_step.input_preview == {"path": "finder_selection"}
    assert open_decision.plan.route_to_studio is False

    reveal_decision = RuntimePlanner().decision(
        "在 Finder 中显示 iCloud 云盘",
        allowed_tools=["desktop.open_path", "desktop.reveal_path"],
    )

    assert reveal_decision.selected_intent.kind == "file_access"
    assert reveal_decision.selected_intent.inputs == {
        "action": "reveal_path",
        "path": "~/Library/Mobile Documents/com~apple~CloudDocs",
    }
    reveal_step = _step_by_id(reveal_decision, "reveal-local-path")
    assert reveal_step.tool_name == "desktop.reveal_path"
    assert reveal_step.action == "reveal_path"
    assert reveal_step.input_preview == {
        "path": "~/Library/Mobile Documents/com~apple~CloudDocs"
    }


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

    search_decision = RuntimePlanner().decision(
        "研究一下 OpenAI 最新新闻并输出报告",
        allowed_tools=["browser.open_url", "artifact.write"],
    )
    assert search_decision.selected_intent.kind == "web_research"
    assert search_decision.selected_intent.inputs["browser_action"] == "open_search"
    assert search_decision.selected_intent.inputs["query"] == "OpenAI 最新新闻"
    assert _step_by_id(search_decision, "open-web-search").input_preview == {
        "url": "https://www.google.com/search?q=OpenAI+%E6%9C%80%E6%96%B0%E6%96%B0%E9%97%BB"
    }

    english_decision = RuntimePlanner().decision(
        "research OpenAI latest news and write a report",
        allowed_tools=["browser.open_url", "artifact.write"],
    )
    assert english_decision.selected_intent.kind == "web_research"
    assert english_decision.selected_intent.inputs["query"] == "openai latest news"


def test_runtime_planner_routes_current_page_browser_actions() -> None:
    screenshot = RuntimePlanner().decision(
        "screenshot current webpage",
        allowed_tools=["browser.screenshot", "screen.capture"],
    )

    assert screenshot.selected_intent.kind == "web_research"
    assert screenshot.selected_intent.inputs == {
        "url_hint": "",
        "browser_action": "screenshot",
        "reason": "user asked to capture the browser page",
    }
    screenshot_step = _step_by_id(screenshot, "capture-current-page")
    assert screenshot_step.tool_name == "browser.screenshot"
    assert screenshot_step.action == "screenshot"
    assert screenshot_step.input_preview == {
        "reason": "user asked to capture the browser page"
    }
    assert screenshot_step.approval_required is False
    assert screenshot.plan.tool_plan.artifacts_expected == ["browser/current-page.png"]

    summary = RuntimePlanner().decision(
        "总结当前网页",
        allowed_tools=["browser.current_page", "browser.extract_text"],
    )

    assert summary.selected_intent.inputs == {
        "url_hint": "",
        "browser_action": "extract_text",
        "presentation": "summary",
    }
    summary_step = _step_by_id(summary, "extract-current-page-text")
    assert summary_step.tool_name == "browser.extract_text"
    assert summary_step.action == "extract_text"
    assert summary.plan.tool_plan.artifacts_expected == []

    english_summary = RuntimePlanner().decision(
        "what is this page about",
        allowed_tools=["browser.current_page", "browser.extract_text"],
    )

    assert english_summary.selected_intent.inputs == {
        "url_hint": "",
        "browser_action": "extract_text",
        "presentation": "summary",
    }
    english_summary_step = _step_by_id(english_summary, "extract-current-page-text")
    assert english_summary_step.tool_name == "browser.extract_text"
    assert english_summary_step.action == "extract_text"

    content = RuntimePlanner().decision(
        "读取当前网页内容",
        allowed_tools=["browser.current_page", "browser.extract_text"],
    )

    content_step = _step_by_id(content, "extract-current-page-text")
    assert content.selected_intent.inputs == {
        "url_hint": "",
        "browser_action": "extract_text",
    }
    assert content_step.tool_name == "browser.extract_text"

    link = RuntimePlanner().decision(
        "读取当前网页链接",
        allowed_tools=["browser.current_page", "browser.extract_text"],
    )

    link_step = _step_by_id(link, "read-current-page")
    assert link.selected_intent.inputs == {
        "url_hint": "",
        "browser_action": "current_page",
    }
    assert link_step.tool_name == "browser.current_page"
    assert link_step.action == "read_current_page"


def test_runtime_planner_routes_current_page_find_actions() -> None:
    static = RuntimePlanner().decision(
        "search current page for hello",
        allowed_tools=["desktop.safe_shortcut", "desktop.safe_type_text"],
    )

    assert static.selected_intent.kind == "web_research"
    assert static.selected_intent.required_capabilities == ["desktop.ui_operation"]
    assert static.selected_intent.inputs == {
        "url_hint": "",
        "browser_action": "find_current_page",
        "query": "hello",
    }
    assert [step.step_id for step in static.plan.tool_plan.steps] == [
        "open-current-page-find",
        "type-current-page-find-query",
    ]
    assert _step_by_id(static, "open-current-page-find").input_preview == {
        "action": "find"
    }
    assert _step_by_id(static, "type-current-page-find-query").input_preview == {
        "text": "hello"
    }

    selected = RuntimePlanner().decision(
        "在当前网页查找当前选中文字",
        allowed_tools=["desktop.safe_shortcut", "desktop.safe_type_text"],
    )

    assert selected.selected_intent.inputs == {
        "url_hint": "",
        "browser_action": "find_current_page",
        "context_source": "selection",
    }
    assert [step.step_id for step in selected.plan.tool_plan.steps] == [
        "copy-selected-page-find-query",
        "open-current-page-find",
        "paste-current-page-find-query",
    ]
    assert [step.input_preview for step in selected.plan.tool_plan.steps] == [
        {"action": "copy"},
        {"action": "find"},
        {"action": "paste"},
    ]

    clipboard = RuntimePlanner().decision(
        "用剪贴板内容查找当前网页",
        allowed_tools=["desktop.safe_shortcut", "clipboard.read"],
    )

    assert clipboard.selected_intent.kind == "web_research"
    assert clipboard.selected_intent.inputs == {
        "url_hint": "",
        "browser_action": "find_current_page",
        "context_source": "clipboard",
    }
    assert [step.input_preview for step in clipboard.plan.tool_plan.steps] == [
        {"action": "find"},
        {"action": "paste"},
    ]

    global_search = RuntimePlanner().decision(
        "search selected text",
        allowed_tools=["desktop.safe_shortcut", "clipboard.read", "browser.open_url"],
    )

    assert global_search.selected_intent.kind == "web_research"
    assert global_search.selected_intent.inputs == {
        "url_hint": "",
        "context_source": "selection",
        "browser_action": "open_search",
    }
    assert [step.step_id for step in global_search.plan.tool_plan.steps] == [
        "copy-selected-browser-context",
        "focus-browser-address-bar",
        "paste-browser-context",
        "submit-browser-context",
    ]


def test_runtime_planner_routes_static_web_search_to_open_url() -> None:
    decision = RuntimePlanner().decision(
        "Can you search Chrome for weather?",
        allowed_tools=["browser.open_url", "browser.open_url_and_extract_text"],
    )
    bare_search = RuntimePlanner().decision(
        "search Chrome for weather",
        allowed_tools=["browser.open_url", "browser.open_url_and_extract_text"],
    )

    assert decision.selected_intent.kind == "web_research"
    assert decision.selected_intent.inputs == {
        "url_hint": "https://www.google.com/search?q=weather",
        "browser_action": "open_search",
        "query": "weather",
    }
    step = _step_by_id(decision, "open-web-search")
    assert step.tool_name == "browser.open_url"
    assert step.input_preview == {"url": "https://www.google.com/search?q=weather"}
    assert bare_search.selected_intent.kind == "web_research"
    assert bare_search.selected_intent.inputs == {
        "url_hint": "https://www.google.com/search?q=weather",
        "browser_action": "open_search",
        "query": "weather",
    }

    chinese = RuntimePlanner().decision(
        "搜索天气",
        allowed_tools=["browser.open_url"],
    )

    assert chinese.selected_intent.inputs == {
        "url_hint": "https://www.google.com/search?q=%E5%A4%A9%E6%B0%94",
        "browser_action": "open_search",
        "query": "天气",
    }
    assert _step_by_id(chinese, "open-web-search").tool_name == "browser.open_url"

    first_result = RuntimePlanner().decision(
        "Chrome 搜索 OpenAI 并打开第一个结果",
        allowed_tools=["browser.open_url", "browser.click"],
    )
    assert first_result.selected_intent.kind == "web_research"
    assert first_result.selected_intent.inputs == {
        "url_hint": "https://www.google.com/search?q=OpenAI",
        "browser_action": "open_search",
        "query": "OpenAI",
        "followup_action": "click_search_result",
        "selector": "search-result=1",
        "click_count": 1,
    }
    assert [step.step_id for step in first_result.plan.tool_plan.steps] == [
        "open-web-search",
        "click-web-search-result",
    ]
    assert _step_by_id(first_result, "open-web-search").input_preview == {
        "url": "https://www.google.com/search?q=OpenAI"
    }
    click_step = _step_by_id(first_result, "click-web-search-result")
    assert click_step.tool_name == "browser.click"
    assert click_step.input_preview == {"selector": "search-result=1", "click_count": 1}
    assert click_step.approval_required is True
    assert click_step.depends_on == ["open-web-search"]

    english_first_result = RuntimePlanner().decision(
        "search Chrome for OpenAI and open first result",
        allowed_tools=["browser.open_url", "browser.click"],
    )
    assert english_first_result.selected_intent.inputs["query"] == "OpenAI"
    assert english_first_result.selected_intent.inputs["followup_action"] == (
        "click_search_result"
    )

    app_search = RuntimePlanner().decision(
        "search WeChat for file transfer",
        allowed_tools=["browser.open_url", "app.focus_and_safe_shortcut"],
    )

    assert app_search.selected_intent.inputs.get("browser_action") != "open_search"
    assert planner_tool_requests(
        "search WeChat for file transfer",
        allowed_tools=["browser.open_url", "app.focus_and_safe_shortcut"],
    ) == []


def test_runtime_planner_routes_explicit_browser_url_open_actions() -> None:
    allowed = [
        "browser.open_url",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
    ]

    https = RuntimePlanner().decision("打开 https://example.com", allowed_tools=allowed)

    assert https.selected_intent.kind == "web_research"
    assert https.selected_intent.inputs == {
        "url_hint": "https://example.com",
        "browser_action": "open_url",
    }
    https_step = _step_by_id(https, "open-web-url")
    assert https_step.tool_name == "browser.open_url"
    assert https_step.input_preview == {"url": "https://example.com"}
    assert https.plan.tool_plan.artifacts_expected == []

    local = RuntimePlanner().decision("打开 127.0.0.1:5173", allowed_tools=allowed)

    assert local.selected_intent.inputs == {
        "url_hint": "http://127.0.0.1:5173",
        "browser_action": "open_url",
    }
    assert _step_by_id(local, "open-web-url").tool_name == "browser.open_url"

    ip_path = RuntimePlanner().decision(
        "open 192.168.1.10:8000/status",
        allowed_tools=allowed,
    )

    assert ip_path.selected_intent.kind == "web_research"
    assert ip_path.selected_intent.inputs == {
        "url_hint": "http://192.168.1.10:8000/status",
        "browser_action": "open_url",
    }

    domain = RuntimePlanner().decision("打开网页 github.com", allowed_tools=allowed)

    assert domain.selected_intent.inputs == {
        "url_hint": "https://github.com",
        "browser_action": "open_url",
    }

    extract = RuntimePlanner().decision("打开 github.com 读一下内容", allowed_tools=allowed)

    assert extract.selected_intent.inputs == {
        "url_hint": "https://github.com",
        "browser_action": "open_url_extract",
    }
    extract_step = _step_by_id(extract, "extract-web-url-text")
    assert extract_step.tool_name == "browser.open_url_and_extract_text"
    assert extract_step.input_preview == {"url": "https://github.com"}

    summary = RuntimePlanner().decision("open github.com and summarize", allowed_tools=allowed)

    assert summary.selected_intent.inputs == {
        "url_hint": "https://github.com",
        "browser_action": "open_url_extract",
        "presentation": "summary",
    }
    assert _step_by_id(summary, "extract-web-url-text").tool_name == (
        "browser.open_url_and_extract_text"
    )

    screenshot = RuntimePlanner().decision(
        "请调研 https://example.com 并截图",
        allowed_tools=allowed,
    )

    assert screenshot.selected_intent.inputs == {
        "url_hint": "https://example.com",
        "browser_action": "open_url_screenshot",
        "reason": "user asked to capture the browser page after opening a URL",
    }
    screenshot_step = _step_by_id(screenshot, "capture-web-url")
    assert screenshot_step.tool_name == "browser.open_url_and_screenshot"
    assert screenshot_step.input_preview == {
        "url": "https://example.com",
        "reason": "user asked to capture the browser page after opening a URL",
    }
    assert screenshot.plan.tool_plan.artifacts_expected == ["browser/current-page.png"]

    research = RuntimePlanner().decision(
        "请调研 https://example.com 并总结报告",
        allowed_tools=allowed,
    )

    assert research.selected_intent.inputs == {"url_hint": "https://example.com"}
    assert _step_by_id(research, "open-or-read-web").tool_name == "browser.open_url_and_extract_text"

    data_file = RuntimePlanner().decision(
        "分析 sales.csv",
        allowed_tools=["browser.open_url", "data.analyze", "workspace.read"],
    )

    assert data_file.selected_intent.kind == "data_analysis"


def test_runtime_planner_tracks_dynamic_web_context_source() -> None:
    decision = RuntimePlanner().decision(
        "search selected text",
        allowed_tools=["desktop.safe_shortcut", "desktop.search_submit", "browser.open_url"],
    )

    assert decision.selected_intent.kind == "web_research"
    assert decision.selected_intent.required_capabilities == ["desktop.ui_operation"]
    assert decision.selected_intent.inputs == {
        "url_hint": "",
        "context_source": "selection",
        "browser_action": "open_search",
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "copy-selected-browser-context",
        "focus-browser-address-bar",
        "paste-browser-context",
        "submit-browser-context",
    ]
    assert _step_by_id(decision, "copy-selected-browser-context").input_preview == {
        "action": "copy"
    }
    assert _step_by_id(decision, "focus-browser-address-bar").input_preview == {
        "action": "focus_address_bar"
    }
    assert _step_by_id(decision, "paste-browser-context").input_preview == {
        "action": "paste"
    }
    assert _step_by_id(decision, "submit-browser-context").tool_name == "desktop.search_submit"


def test_runtime_planner_routes_dynamic_context_url_open_actions() -> None:
    selected = RuntimePlanner().decision(
        "打开选中的链接",
        allowed_tools=["desktop.safe_shortcut", "desktop.search_submit"],
    )

    assert selected.selected_intent.kind == "web_research"
    assert selected.selected_intent.inputs == {
        "url_hint": "",
        "context_source": "selection",
        "browser_action": "open_url",
    }
    assert [step.step_id for step in selected.plan.tool_plan.steps] == [
        "copy-selected-browser-context",
        "focus-browser-address-bar",
        "paste-browser-context",
        "submit-browser-context",
    ]

    clipboard = RuntimePlanner().decision(
        "open clipboard link",
        allowed_tools=["desktop.safe_shortcut", "desktop.search_submit"],
    )

    assert clipboard.selected_intent.kind == "web_research"
    assert clipboard.selected_intent.inputs == {
        "url_hint": "",
        "context_source": "clipboard",
        "browser_action": "open_url",
    }
    assert [step.step_id for step in clipboard.plan.tool_plan.steps] == [
        "focus-browser-address-bar",
        "paste-browser-context",
        "submit-browser-context",
    ]


def test_runtime_planner_report_generation_prefers_workspace_list_for_context() -> None:
    decision = RuntimePlanner().decision(
        "写一份项目总结报告",
        allowed_tools=["workspace.read", "workspace.list", "artifact.write"],
    )

    assert decision.selected_intent.kind == "report_generation"
    assert _step_by_id(decision, "gather-context").tool_name == "workspace.list"

    clipboard = RuntimePlanner().decision(
        "把剪贴板内容做成报告",
        allowed_tools=["clipboard.read", "artifact.write"],
    )
    assert clipboard.selected_intent.kind == "report_generation"
    assert clipboard.selected_intent.inputs == {"context_source": "clipboard"}
    assert [step.step_id for step in clipboard.plan.tool_plan.steps] == [
        "read-report-context",
        "write-report-artifact",
    ]
    assert _step_by_id(clipboard, "read-report-context").tool_name == "clipboard.read"
    assert _step_by_id(clipboard, "write-report-artifact").input_preview == {
        "path": "report.md",
        "body_source": "clipboard",
    }

    read_only = RuntimePlanner().decision(
        "读取剪贴板",
        allowed_tools=["clipboard.read", "artifact.write"],
    )
    assert read_only.selected_intent.kind == "clipboard_operation"


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


def test_runtime_planner_extracts_postposed_chinese_app_names() -> None:
    cases = (
        ("把 Arc 打开", "Arc", "app.open"),
        ("帮我把 Linear 启动起来", "Linear", "app.open"),
        ("把微信打开", "微信", "app.open"),
        ("把 Slack 切到前台", "Slack", "app.focus"),
        ("把 Obsidian 聚焦", "Obsidian", "app.focus"),
        ("帮我打开一下 CleanMyMac 可以吗", "CleanMyMac", "app.open"),
        ("麻烦启动下飞书好吗", "飞书", "app.open"),
        ("能不能切到 Slack 一下", "Slack", "app.focus"),
    )

    for prompt, expected_app_name, expected_tool in cases:
        decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=["desktop.list_apps", "app.open", "app.focus", "desktop.active_window"],
        )

        assert decision.selected_intent.kind == "desktop_operation"
        assert decision.selected_intent.inputs["app_name_hint"] == expected_app_name
        assert _step_by_id(decision, "discover-desktop-state").input_preview == {
            "query": expected_app_name,
            "limit": 20,
        }
        assert _step_by_id(decision, "open-or-focus-app").tool_name == expected_tool
        assert _step_by_id(decision, "open-or-focus-app").input_preview == {
            "app_name": expected_app_name,
        }


def test_runtime_planner_keeps_postposed_app_name_for_app_scoped_shortcut() -> None:
    decision = RuntimePlanner().decision(
        "把 Chrome 打开然后新建标签页",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.active_window",
        ],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "Chrome"
    assert _step_by_id(decision, "discover-desktop-state").input_preview == {
        "query": "Chrome",
        "limit": 20,
    }
    assert _step_by_id(decision, "operate-foreground-ui").tool_name == (
        "app.open_and_safe_shortcut"
    )
    assert _step_by_id(decision, "operate-foreground-ui").input_preview == {
        "app_name": "Chrome",
        "action": "new_tab",
    }


def test_runtime_planner_extracts_english_focus_and_app_prefixes() -> None:
    cases = (
        ("bring Slack to front", "Slack", "app.focus"),
        ("bring Slack forward", "Slack", "app.focus"),
        ("activate Slack", "Slack", "app.focus"),
        ("switch Slack to front", "Slack", "app.focus"),
        ("open the app Raycast", "Raycast", "app.open"),
        ("start the app Linear", "Linear", "app.open"),
        ("focus Obsidian app", "Obsidian", "app.focus"),
        ("launch Arc Browser app", "Arc Browser", "app.open"),
    )

    for prompt, expected_app_name, expected_tool in cases:
        decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=["desktop.list_apps", "app.open", "app.focus", "desktop.active_window"],
        )

        assert decision.selected_intent.kind == "desktop_operation"
        assert decision.selected_intent.inputs["app_name_hint"] == expected_app_name
        assert _step_by_id(decision, "discover-desktop-state").input_preview == {
            "query": expected_app_name,
            "limit": 20,
        }
        assert _step_by_id(decision, "open-or-focus-app").tool_name == expected_tool
        assert _step_by_id(decision, "open-or-focus-app").input_preview == {
            "app_name": expected_app_name,
        }


def test_runtime_planner_treats_music_app_open_as_desktop_open() -> None:
    decision = RuntimePlanner().decision(
        "打开 Apple Music",
        allowed_tools=["desktop.list_apps", "app.open", "media.apple_music_open_and_play"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    discover = _step_by_id(decision, "discover-desktop-state")
    assert discover.tool_name == "desktop.list_apps"
    assert discover.input_preview == {"query": "Apple Music", "limit": 20}
    assert _step_by_id(decision, "open-or-focus-app").tool_name == "app.open"


def test_runtime_planner_keeps_app_name_before_chinese_followup_capture() -> None:
    decision = RuntimePlanner().decision(
        "打开 Apple Music，然后看看界面",
        allowed_tools=[
            "desktop.list_apps",
            "app.open",
            "screen.capture",
            "desktop.active_window",
        ],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "Apple Music"
    assert _step_by_id(decision, "discover-desktop-state").input_preview == {
        "query": "Apple Music",
        "limit": 20,
    }
    assert _step_by_id(decision, "open-or-focus-app").input_preview == {
        "app_name": "Apple Music",
    }
    assert _step_by_id(decision, "capture-screen").depends_on == ["open-or-focus-app"]


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

    for prompt in ("查看当前应用所有窗口", "显示所有窗口"):
        generic_decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=["desktop.list_apps", "desktop.windows"],
        )

        assert generic_decision.selected_intent.kind == "desktop_operation"
        assert generic_decision.selected_intent.inputs["app_name_hint"] == ""
        assert generic_decision.selected_intent.inputs["operation_hint"] == "list_windows"
        assert generic_decision.selected_intent.inputs["window_list_hint"] == {}
        assert "app_management_hint" not in generic_decision.selected_intent.inputs
        generic_list_windows = _step_by_id(generic_decision, "list-app-windows")
        assert generic_list_windows.tool_name == "desktop.windows"
        assert generic_list_windows.input_preview == {}
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

    polite_current = RuntimePlanner().decision(
        "你能看看现在有哪些按钮吗",
        allowed_tools=["desktop.active_window", "app.focus", "desktop.ui_elements"],
    )
    assert polite_current.selected_intent.kind == "desktop_operation"
    assert polite_current.selected_intent.inputs["app_name_hint"] == ""
    assert polite_current.selected_intent.inputs["ui_inspection_hint"] == {
        "role_filter": "button",
        "limit": 80,
    }
    assert [step.step_id for step in polite_current.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "read-foreground-ui",
    ]


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

    current_interface = RuntimePlanner().decision(
        "Chrome 当前界面有哪些按钮",
        allowed_tools=["desktop.list_apps", "app.focus", "desktop.ui_elements"],
    )
    assert current_interface.selected_intent.kind == "desktop_operation"
    assert current_interface.selected_intent.inputs["app_name_hint"] == "Chrome"
    assert current_interface.selected_intent.inputs["ui_inspection_hint"] == {
        "role_filter": "button",
        "limit": 80,
        "app_name": "Chrome",
    }
    assert _step_by_id(current_interface, "discover-desktop-state").input_preview == {
        "query": "Chrome",
        "limit": 20,
    }
    assert _step_by_id(current_interface, "open-or-focus-app").input_preview == {
        "app_name": "Chrome",
    }
    assert _step_by_id(current_interface, "read-foreground-ui").depends_on == [
        "open-or-focus-app"
    ]


def test_runtime_planner_cleans_prefixed_app_ui_inspection() -> None:
    decision = RuntimePlanner().decision(
        "打开微信看看有什么按钮",
        allowed_tools=["desktop.list_apps", "app.focus", "desktop.ui_elements"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "微信"
    assert decision.selected_intent.inputs["ui_inspection_hint"] == {
        "role_filter": "button",
        "limit": 80,
        "app_name": "微信",
    }
    assert _step_by_id(decision, "discover-desktop-state").input_preview == {
        "query": "微信",
        "limit": 20,
    }
    assert _step_by_id(decision, "open-or-focus-app").input_preview == {
        "app_name": "微信"
    }
    assert _step_by_id(decision, "read-foreground-ui").depends_on == ["open-or-focus-app"]

    open_decision = RuntimePlanner().decision(
        "打开微信看看有什么按钮",
        allowed_tools=["desktop.list_apps", "app.open", "app.focus", "desktop.ui_elements"],
    )
    assert _step_by_id(open_decision, "open-or-focus-app").tool_name == "app.open"
    assert _step_by_id(open_decision, "open-or-focus-app").input_preview == {
        "app_name": "微信"
    }


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
    assert decision.selected_intent.inputs["app_name_hint"] == ""
    assert [step.step_id for step in decision.plan.tool_plan.steps] == ["capture-screen"]
    capture = _step_by_id(decision, "capture-screen")
    assert capture.tool_name == "screen.capture"
    assert capture.action == "capture_screen"
    assert capture.input_preview == {"reason": "user asked to capture the screen"}
    assert capture.depends_on == []
    assert capture.approval_required is False


def test_runtime_planner_does_not_treat_current_screen_as_app_name() -> None:
    decision = RuntimePlanner().decision(
        "帮我看看现在屏幕",
        allowed_tools=["desktop.list_apps", "screen.capture", "desktop.active_window"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == ""
    assert [step.step_id for step in decision.plan.tool_plan.steps] == ["capture-screen"]
    assert _step_by_id(decision, "capture-screen").tool_name == "screen.capture"

    english_decision = RuntimePlanner().decision(
        "look at my screen",
        allowed_tools=["desktop.list_apps", "app.focus", "screen.capture"],
    )
    assert english_decision.selected_intent.inputs["app_name_hint"] == ""
    assert [step.step_id for step in english_decision.plan.tool_plan.steps] == [
        "capture-screen"
    ]

    current_interface = RuntimePlanner().decision(
        "看一下我现在的界面",
        allowed_tools=["desktop.list_apps", "app.focus", "screen.capture"],
    )
    assert current_interface.selected_intent.inputs["app_name_hint"] == ""
    assert current_interface.selected_intent.inputs["screen_capture_hint"] == {
        "reason": "user asked to capture the screen",
    }
    assert [step.step_id for step in current_interface.plan.tool_plan.steps] == [
        "capture-screen"
    ]


def test_runtime_planner_does_not_treat_current_window_as_app_for_foreground_input() -> None:
    decision = RuntimePlanner().decision(
        "在当前窗口输入 hello 并回车",
        allowed_tools=[
            "desktop.running_apps",
            "desktop.safe_type_text",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == ""
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "operate-foreground-ui",
        "submit-foreground-ui",
        "verify-desktop-result",
    ]
    assert _step_by_id(decision, "discover-desktop-state").tool_name == "desktop.running_apps"
    assert _step_by_id(decision, "operate-foreground-ui").tool_name == "desktop.safe_type_text"
    assert _step_by_id(decision, "operate-foreground-ui").input_preview == {"text": "hello"}
    assert _step_by_id(decision, "operate-foreground-ui").depends_on == [
        "discover-desktop-state"
    ]


def test_runtime_planner_cleans_current_interface_from_app_capture_hint() -> None:
    decision = RuntimePlanner().decision(
        "看一下 Chrome 当前界面",
        allowed_tools=["desktop.list_apps", "app.focus", "screen.capture"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "Chrome"
    assert _step_by_id(decision, "discover-desktop-state").input_preview == {
        "query": "Chrome",
        "limit": 20,
    }
    assert _step_by_id(decision, "open-or-focus-app").input_preview == {
        "app_name": "Chrome",
    }
    assert _step_by_id(decision, "capture-screen").tool_name == "screen.capture"

    prefix_decision = RuntimePlanner().decision(
        "Chrome 看看界面",
        allowed_tools=["desktop.list_apps", "app.focus", "screen.capture"],
    )
    assert prefix_decision.selected_intent.inputs["app_name_hint"] == "Chrome"
    assert _step_by_id(prefix_decision, "open-or-focus-app").input_preview == {
        "app_name": "Chrome"
    }
    assert _step_by_id(prefix_decision, "capture-screen").depends_on == [
        "open-or-focus-app"
    ]


def test_runtime_planner_focuses_app_before_app_scoped_screen_capture() -> None:
    decision = RuntimePlanner().decision(
        "看一下 Slack 界面",
        allowed_tools=["desktop.list_apps", "app.focus", "screen.capture"],
    )
    suffix_decision = RuntimePlanner().decision(
        "Slack 截屏",
        allowed_tools=["desktop.list_apps", "app.focus", "screen.capture"],
    )
    prefix_decision = RuntimePlanner().decision(
        "截取 Slack 的界面",
        allowed_tools=["desktop.list_apps", "app.focus", "screen.capture"],
    )
    current_window_decision = RuntimePlanner().decision(
        "当前窗口截图",
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
    for capture_decision in (suffix_decision, prefix_decision):
        assert capture_decision.selected_intent.inputs["app_name_hint"] == "Slack"
        assert capture_decision.selected_intent.inputs["operation_hint"] == "capture_screen"
        assert _step_by_id(capture_decision, "open-or-focus-app").input_preview == {
            "app_name": "Slack"
        }
        assert _step_by_id(capture_decision, "capture-screen").depends_on == [
            "open-or-focus-app"
        ]
    assert current_window_decision.selected_intent.inputs["app_name_hint"] == ""
    assert [step.step_id for step in current_window_decision.plan.tool_plan.steps] == [
        "capture-screen"
    ]

    open_decision = RuntimePlanner().decision(
        "打开 Slack 然后截图",
        allowed_tools=["desktop.list_apps", "app.open", "app.focus", "screen.capture"],
    )
    assert _step_by_id(open_decision, "open-or-focus-app").tool_name == "app.open"
    assert _step_by_id(open_decision, "capture-screen").depends_on == ["open-or-focus-app"]


def test_runtime_planner_routes_named_app_management_to_app_control() -> None:
    decision = RuntimePlanner().decision(
        "隐藏 Slack",
        allowed_tools=["desktop.list_apps", "app.hide", "desktop.running_apps"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.risk_level == "low"
    assert decision.selected_intent.inputs["app_name_hint"] == "Slack"
    assert decision.selected_intent.inputs["operation_hint"] == "hide_app"
    assert decision.selected_intent.inputs["app_management_hint"] == {
        "action": "hide",
        "app_name": "Slack",
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "manage-app",
        "verify-desktop-result",
    ]
    manage = _step_by_id(decision, "manage-app")
    assert manage.tool_name == "app.hide"
    assert manage.action == "hide_app"
    assert manage.input_preview == {"app_name": "Slack"}
    assert manage.approval_required is False
    assert _step_by_id(decision, "verify-desktop-result").depends_on == ["manage-app"]


def test_runtime_planner_sequences_app_open_or_focus_before_app_management() -> None:
    cases = [
        ("打开 Slack 然后隐藏", "open", "app.open", "app.hide", False),
        ("切到 Slack 然后隐藏", "focus", "app.focus", "app.hide", False),
        ("open Chrome then minimize", "open", "app.open", "app.minimize", False),
        ("打开 Slack 然后退出", "open", "app.open", "app.quit", True),
    ]

    for prompt, prepare_mode, prepare_tool, manage_tool, approval_required in cases:
        decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=[
                "desktop.list_apps",
                "app.open",
                "app.focus",
                "app.hide",
                "app.minimize",
                "app.quit",
                "desktop.running_apps",
            ],
        )

        app_name = "Chrome" if "Chrome" in prompt else "Slack"
        assert decision.selected_intent.kind == "desktop_operation"
        assert decision.selected_intent.inputs["app_name_hint"] == app_name
        assert decision.selected_intent.inputs["app_management_hint"]["app_name"] == app_name
        assert decision.selected_intent.inputs["app_management_prepare_mode"] == prepare_mode
        assert [step.step_id for step in decision.plan.tool_plan.steps] == [
            "discover-desktop-state",
            "open-or-focus-app",
            "manage-app",
            "verify-desktop-result",
        ]
        assert _step_by_id(decision, "discover-desktop-state").input_preview == {
            "query": app_name,
            "limit": 20,
        }
        prepare = _step_by_id(decision, "open-or-focus-app")
        assert prepare.tool_name == prepare_tool
        assert prepare.input_preview == {"app_name": app_name}
        manage = _step_by_id(decision, "manage-app")
        assert manage.tool_name == manage_tool
        assert manage.input_preview == {"app_name": app_name}
        assert manage.depends_on == ["open-or-focus-app"]
        assert manage.approval_required is approval_required


def test_runtime_planner_marks_named_app_quit_as_approval_required() -> None:
    decision = RuntimePlanner().decision(
        "退出 Slack",
        allowed_tools=["desktop.list_apps", "app.quit", "desktop.running_apps"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.risk_level == "high"
    assert decision.selected_intent.inputs["operation_hint"] == "quit_app"
    manage = _step_by_id(decision, "manage-app")
    assert manage.tool_name == "app.quit"
    assert manage.action == "quit_app"
    assert manage.risk_level == "high"
    assert manage.approval_required is True
    assert decision.plan.tool_plan.approvals_required == ["manage-app"]


def test_runtime_planner_routes_foreground_window_minimize_to_desktop_tool() -> None:
    decision = RuntimePlanner().decision(
        "最小化当前窗口",
        allowed_tools=["desktop.active_window", "desktop.minimize_window"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.risk_level == "low"
    assert decision.selected_intent.inputs["app_name_hint"] == ""
    assert decision.selected_intent.inputs["operation_hint"] == "minimize_window"
    assert decision.selected_intent.inputs["foreground_management_hint"] == {
        "action": "minimize_window",
        "scope": "window",
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "manage-foreground",
        "verify-desktop-result",
    ]
    manage = _step_by_id(decision, "manage-foreground")
    assert manage.tool_name == "desktop.minimize_window"
    assert manage.action == "minimize_window"
    assert manage.risk_level == "low"
    assert manage.approval_required is False
    assert _step_by_id(decision, "verify-desktop-result").depends_on == [
        "manage-foreground"
    ]

    for prompt in (
        "把当前应用最小化",
        "最小化当前应用",
        "Can you minimize the current app?",
    ):
        current_app = RuntimePlanner().decision(
            prompt,
            allowed_tools=["desktop.active_window", "desktop.minimize_window", "app.minimize"],
        )

        assert current_app.selected_intent.kind == "desktop_operation"
        assert current_app.selected_intent.inputs["app_name_hint"] == ""
        assert current_app.selected_intent.inputs["foreground_management_hint"] == {
            "action": "minimize_window",
            "scope": "window",
        }
        assert _step_by_id(current_app, "manage-foreground").tool_name == (
            "desktop.minimize_window"
        )

    named_app = RuntimePlanner().decision(
        "最小化 Safari",
        allowed_tools=["desktop.list_apps", "app.minimize", "desktop.running_apps"],
    )
    assert named_app.selected_intent.inputs["app_management_hint"] == {
        "action": "minimize",
        "app_name": "Safari",
    }
    assert _step_by_id(named_app, "manage-app").tool_name == "app.minimize"


def test_runtime_planner_marks_foreground_close_and_quit_as_approval_required() -> None:
    close_decision = RuntimePlanner().decision(
        "关闭当前窗口",
        allowed_tools=["desktop.active_window", "desktop.close_window"],
    )
    quit_decision = RuntimePlanner().decision(
        "退出当前应用",
        allowed_tools=["desktop.active_window", "desktop.quit_app"],
    )

    assert close_decision.selected_intent.risk_level == "high"
    assert close_decision.selected_intent.inputs["operation_hint"] == "close_window"
    close_step = _step_by_id(close_decision, "manage-foreground")
    assert close_step.tool_name == "desktop.close_window"
    assert close_step.action == "close_window"
    assert close_step.risk_level == "high"
    assert close_step.approval_required is True
    assert close_decision.plan.tool_plan.approvals_required == ["manage-foreground"]

    assert quit_decision.selected_intent.risk_level == "high"
    assert quit_decision.selected_intent.inputs["operation_hint"] == "quit_app"
    quit_step = _step_by_id(quit_decision, "manage-foreground")
    assert quit_step.tool_name == "desktop.quit_app"
    assert quit_step.action == "quit_app"
    assert quit_step.risk_level == "high"
    assert quit_step.approval_required is True
    assert quit_decision.plan.tool_plan.approvals_required == ["manage-foreground"]


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


def test_runtime_planner_extracts_leading_app_for_ui_operations() -> None:
    type_decision = RuntimePlanner().decision(
        "Slack 点击搜索框输入 Alice 并回车",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_type_into_ui_element",
            "desktop.submit_foreground",
        ],
    )
    click_decision = RuntimePlanner().decision(
        "微信点击搜索",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_click_ui_element",
            "desktop.ui_elements",
        ],
    )
    focus_type_decision = RuntimePlanner().decision(
        "切到 Slack 在搜索框输入 Alice",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_type_into_ui_element",
            "desktop.ui_elements",
        ],
    )
    in_type_decision = RuntimePlanner().decision(
        "在 Slack 搜索框输入 Alice",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_type_into_ui_element",
            "desktop.ui_elements",
        ],
    )
    foreground_click = RuntimePlanner().decision(
        "点击发送按钮",
        allowed_tools=["desktop.click_ui_element"],
    )

    assert type_decision.selected_intent.inputs["app_name_hint"] == "Slack"
    assert type_decision.selected_intent.inputs["operation_hint"] == "click"
    type_step = _step_by_id(type_decision, "operate-foreground-ui")
    assert type_step.tool_name == "app.open_and_type_into_ui_element"
    assert type_step.input_preview == {
        "app_name": "Slack",
        "target": "搜索框",
        "text": "Alice",
        "role_filter": "text",
        "limit": 80,
    }
    assert _step_by_id(type_decision, "submit-foreground-ui").approval_required is True

    for app_type_decision in (focus_type_decision, in_type_decision):
        assert app_type_decision.selected_intent.inputs["app_name_hint"] == "Slack"
        app_type_step = _step_by_id(app_type_decision, "operate-foreground-ui")
        assert app_type_step.tool_name == "app.focus_and_type_into_ui_element"
        assert app_type_step.input_preview == {
            "app_name": "Slack",
            "target": "搜索框",
            "text": "Alice",
            "role_filter": "text",
            "limit": 80,
        }

    assert click_decision.selected_intent.inputs["app_name_hint"] == "微信"
    assert click_decision.selected_intent.inputs["operation_hint"] == "click"
    click_step = _step_by_id(click_decision, "operate-foreground-ui")
    assert click_step.tool_name == "app.open_and_click_ui_element"
    assert click_step.input_preview == {
        "app_name": "微信",
        "target": "搜索",
        "role_filter": "",
        "click_count": 1,
        "limit": 80,
    }

    assert foreground_click.selected_intent.inputs["app_name_hint"] == ""
    assert _step_by_id(foreground_click, "operate-foreground-ui").tool_name == (
        "desktop.click_ui_element"
    )


def test_runtime_planner_routes_safe_shortcut_without_approval() -> None:
    decision = RuntimePlanner().decision(
        "刷新当前页面",
        allowed_tools=["desktop.active_window", "desktop.safe_shortcut", "desktop.ui_elements"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.risk_level == "low"
    assert decision.selected_intent.inputs["operation_hint"] == "safe_shortcut"
    assert decision.selected_intent.inputs["safe_shortcut_hint"] == {"action": "refresh"}
    operation = _step_by_id(decision, "operate-foreground-ui")
    assert operation.tool_name == "desktop.safe_shortcut"
    assert operation.action == "shortcut"
    assert operation.input_preview == {"action": "refresh"}
    assert operation.risk_level == "low"
    assert operation.approval_required is False
    assert _step_by_id(decision, "verify-desktop-result").depends_on == [
        "operate-foreground-ui"
    ]


def test_runtime_planner_routes_foreground_browser_safe_shortcuts() -> None:
    cases = [
        ("refresh the current page", "refresh"),
        ("open a new tab", "new_tab"),
        ("新开一个标签页", "new_tab"),
        ("关闭当前标签页", "close_tab"),
        ("切到下一个标签页", "next_tab"),
        ("打开浏览器历史记录", "show_history"),
        ("打开开发者工具", "open_devtools"),
        ("把当前网页加入书签", "bookmark_page"),
    ]

    for prompt, action in cases:
        decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=[
                "desktop.active_window",
                "desktop.safe_shortcut",
                "desktop.ui_elements",
            ],
        )

        assert decision.selected_intent.kind == "desktop_operation"
        assert decision.selected_intent.inputs.get("app_name_hint", "") == ""
        assert "app_management_hint" not in decision.selected_intent.inputs
        assert decision.selected_intent.inputs["operation_hint"] == "safe_shortcut"
        assert decision.selected_intent.inputs["safe_shortcut_hint"] == {"action": action}
        operation = _step_by_id(decision, "operate-foreground-ui")
        assert operation.tool_name == "desktop.safe_shortcut"
        assert operation.input_preview == {"action": action}


def test_runtime_planner_routes_foreground_application_windows_shortcut() -> None:
    for prompt in ("显示当前应用窗口", "显示当前应用所有窗口", "show app windows"):
        decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=[
                "desktop.active_window",
                "desktop.safe_shortcut",
                "desktop.ui_elements",
            ],
        )

        assert decision.selected_intent.kind == "desktop_operation"
        assert decision.selected_intent.inputs == {
            "app_name_hint": "",
            "operation_hint": "safe_shortcut",
            "safe_shortcut_hint": {"action": "application_windows"},
        }
        operation = _step_by_id(decision, "operate-foreground-ui")
        assert operation.tool_name == "desktop.safe_shortcut"
        assert operation.input_preview == {"action": "application_windows"}


def test_runtime_planner_routes_app_scoped_search_to_desktop_sequence() -> None:
    decision = RuntimePlanner().decision(
        "打开 Notion 并搜索 周报",
        allowed_tools=[
            "desktop.list_apps",
            "app.open",
            "desktop.safe_shortcut",
            "desktop.click_ui_element",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.ui_elements",
            "browser.open_url",
        ],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "Notion"
    assert decision.selected_intent.inputs["app_search_hint"] == {
        "query": "周报",
        "target": "搜索",
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "open-or-focus-app",
        "focus-app-search-field",
        "type-app-search-query",
        "submit-app-search",
        "verify-desktop-result",
    ]
    assert _step_by_id(decision, "focus-app-search-field").tool_name == "desktop.safe_shortcut"
    assert _step_by_id(decision, "focus-app-search-field").input_preview == {
        "action": "find",
    }
    assert _step_by_id(decision, "open-or-focus-app").tool_name == "app.open"
    assert _step_by_id(decision, "type-app-search-query").input_preview == {
        "text": "周报"
    }
    assert _step_by_id(decision, "submit-app-search").tool_name == "desktop.search_submit"
    assert _step_by_id(decision, "submit-app-search").approval_required is False

    leading = RuntimePlanner().decision(
        "Finder 找下载文件",
        allowed_tools=[
            "desktop.list_apps",
            "app.open",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
        ],
    )

    assert leading.selected_intent.kind == "desktop_operation"
    assert leading.selected_intent.inputs["app_name_hint"] == "Finder"
    assert leading.selected_intent.inputs["app_search_hint"] == {
        "app_name": "Finder",
        "query": "下载文件",
        "target": "搜索",
    }

    scoped_search = RuntimePlanner().decision(
        "在微信搜索文件传输助手",
        allowed_tools=[
            "desktop.list_apps",
            "app.open",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
        ],
    )
    assert scoped_search.selected_intent.kind == "desktop_operation"
    assert scoped_search.selected_intent.inputs["app_name_hint"] == "微信"
    assert scoped_search.selected_intent.inputs["app_search_hint"] == {
        "query": "文件传输助手",
        "target": "搜索",
    }
    assert _step_by_id(scoped_search, "open-or-focus-app").tool_name == "app.focus"

    english_scoped_search = RuntimePlanner().decision(
        "search WeChat for file transfer",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.ui_elements",
            "browser.open_url",
        ],
    )
    assert english_scoped_search.selected_intent.kind == "desktop_operation"
    assert english_scoped_search.selected_intent.inputs["app_name_hint"] == "WeChat"
    assert english_scoped_search.selected_intent.inputs["app_search_hint"] == {
        "app_name": "WeChat",
        "query": "file transfer",
        "target": "Search",
    }
    assert _step_by_id(english_scoped_search, "open-or-focus-app").tool_name == "app.focus"

    english_scoped_search_with_preposition = RuntimePlanner().decision(
        "search in WeChat for file transfer",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.ui_elements",
            "browser.open_url",
        ],
    )
    assert english_scoped_search_with_preposition.selected_intent.kind == "desktop_operation"
    assert (
        english_scoped_search_with_preposition.selected_intent.inputs["app_name_hint"]
        == "WeChat"
    )
    assert english_scoped_search_with_preposition.selected_intent.inputs["app_search_hint"] == {
        "app_name": "WeChat",
        "query": "file transfer",
        "target": "Search",
    }

    focused_search = RuntimePlanner().decision(
        "切到微信，搜索张三",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "browser.open_url",
        ],
    )
    assert focused_search.selected_intent.kind == "desktop_operation"
    assert focused_search.selected_intent.inputs["app_name_hint"] == "微信"
    assert focused_search.selected_intent.inputs["app_search_hint"] == {
        "query": "张三",
        "target": "搜索",
    }
    assert _step_by_id(focused_search, "open-or-focus-app").tool_name == "app.focus"

    command_palette = RuntimePlanner().decision(
        "切到 Obsidian 打开命令面板输入 Toggle reading view 并回车",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
    )
    assert command_palette.selected_intent.kind == "desktop_operation"
    assert command_palette.selected_intent.inputs["app_name_hint"] == "Obsidian"
    assert command_palette.selected_intent.inputs["command_palette_hint"] == {
        "app_name": "Obsidian",
        "mode": "focus",
        "action": "obsidian_command_palette",
        "text": "Toggle reading view",
        "submit": True,
    }
    assert [step.step_id for step in command_palette.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "open-app-command-palette",
        "type-command-palette-query",
        "submit-command-palette",
        "verify-desktop-result",
    ]
    assert _step_by_id(command_palette, "open-app-command-palette").tool_name == (
        "app.focus_and_safe_shortcut"
    )
    assert _step_by_id(command_palette, "open-app-command-palette").input_preview == {
        "app_name": "Obsidian",
        "action": "obsidian_command_palette",
    }
    assert _step_by_id(command_palette, "type-command-palette-query").input_preview == {
        "text": "Toggle reading view"
    }
    assert _step_by_id(command_palette, "submit-command-palette").tool_name == (
        "desktop.submit_foreground"
    )

    open_command_palette = RuntimePlanner().decision(
        "打开 Obsidian 命令面板",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.ui_elements",
        ],
    )
    assert open_command_palette.selected_intent.kind == "desktop_operation"
    assert open_command_palette.selected_intent.inputs["app_name_hint"] == "Obsidian"
    assert open_command_palette.selected_intent.inputs["command_palette_hint"] == {
        "app_name": "Obsidian",
        "mode": "open",
        "action": "obsidian_command_palette",
    }
    assert [step.step_id for step in open_command_palette.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "open-app-command-palette",
        "verify-desktop-result",
    ]
    assert _step_by_id(open_command_palette, "open-app-command-palette").tool_name == (
        "app.open_and_safe_shortcut"
    )
    assert _step_by_id(open_command_palette, "open-app-command-palette").input_preview == {
        "app_name": "Obsidian",
        "action": "obsidian_command_palette",
    }

    vscode_command_palette = RuntimePlanner().decision(
        "打开 VS Code 命令面板",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.ui_elements",
        ],
    )
    assert vscode_command_palette.selected_intent.kind == "desktop_operation"
    assert vscode_command_palette.selected_intent.inputs["app_name_hint"] == (
        "Visual Studio Code"
    )
    assert vscode_command_palette.selected_intent.inputs["command_palette_hint"] == {
        "app_name": "Visual Studio Code",
        "mode": "open",
        "action": "command_palette",
    }
    assert planner_direct_tool_requests(
        "打开 VS Code 命令面板",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.ui_elements",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]

    finder_file_search = RuntimePlanner().decision(
        "在 Finder 搜索 budget.xlsx",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.ui_elements",
            "data.analyze",
        ],
    )
    assert finder_file_search.selected_intent.kind == "desktop_operation"
    assert finder_file_search.selected_intent.inputs["app_name_hint"] == "Finder"
    assert finder_file_search.selected_intent.inputs["app_search_hint"] == {
        "query": "budget.xlsx",
        "target": "搜索",
    }
    assert _step_by_id(finder_file_search, "open-or-focus-app").tool_name == "app.focus"
    assert _step_by_id(finder_file_search, "type-app-search-query").input_preview == {
        "text": "budget.xlsx"
    }

    finder_find_file = RuntimePlanner().decision(
        "在 Finder 查找 sales.csv",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.ui_elements",
            "data.analyze",
        ],
    )
    assert finder_find_file.selected_intent.kind == "desktop_operation"
    assert finder_find_file.selected_intent.inputs["app_search_hint"] == {
        "query": "sales.csv",
        "target": "搜索",
    }

    first_result = RuntimePlanner().decision(
        "在 Slack 搜索 Alice 并选择第一个结果",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.click_ui_element",
            "desktop.ui_elements",
        ],
    )
    assert first_result.selected_intent.inputs["app_search_hint"] == {
        "query": "Alice",
        "target": "搜索",
    }
    result_click = _step_by_id(first_result, "select-app-search-result")
    assert result_click.tool_name == "desktop.click_ui_element"
    assert result_click.input_preview == {
        "target": "第一个结果",
        "role_filter": "",
        "limit": 80,
        "click_count": 1,
    }
    assert result_click.approval_required is True
    assert _step_by_id(first_result, "verify-desktop-result").depends_on == [
        "select-app-search-result"
    ]

    arrow_confirm = RuntimePlanner().decision(
        "在 Slack 搜索 Alice 后按下箭头再确认",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.safe_key",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
    )
    assert arrow_confirm.selected_intent.inputs["app_search_hint"] == {
        "query": "Alice",
        "target": "搜索",
    }
    assert _step_by_id(arrow_confirm, "select-app-search-result-with-key").input_preview == {
        "action": "arrow_down",
        "repeat_count": 1,
    }
    confirm = _step_by_id(arrow_confirm, "confirm-app-search-result")
    assert confirm.tool_name == "desktop.submit_foreground"
    assert confirm.input_preview == {"action": "confirm"}
    assert confirm.approval_required is True


def test_runtime_planner_routes_browser_internal_pages_to_desktop_sequence() -> None:
    browser_internal = RuntimePlanner().decision(
        "打开 Chrome 下载内容",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.ui_elements",
            "system.settings_open",
            "desktop.open_path",
        ],
    )

    assert browser_internal.selected_intent.kind == "desktop_operation"
    assert browser_internal.selected_intent.inputs["app_name_hint"] == "Chrome"
    assert browser_internal.selected_intent.inputs["browser_internal_page_hint"] == {
        "app_name": "Chrome",
        "surface": "downloads",
        "mode": "open",
        "url": "chrome://downloads/",
    }
    assert [step.step_id for step in browser_internal.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "focus-browser-address-bar",
        "type-browser-internal-url",
        "submit-browser-internal-url",
        "verify-desktop-result",
    ]
    assert _step_by_id(browser_internal, "focus-browser-address-bar").tool_name == (
        "app.open_and_safe_shortcut"
    )
    assert _step_by_id(browser_internal, "focus-browser-address-bar").input_preview == {
        "app_name": "Chrome",
        "action": "focus_address_bar",
    }
    assert _step_by_id(browser_internal, "type-browser-internal-url").input_preview == {
        "text": "chrome://downloads/"
    }

    browser_settings = RuntimePlanner().decision(
        "打开 Chrome 设置",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.ui_elements",
            "system.settings_open",
        ],
    )
    assert browser_settings.selected_intent.kind == "desktop_operation"
    assert browser_settings.selected_intent.inputs["browser_internal_page_hint"] == {
        "app_name": "Chrome",
        "surface": "settings",
        "mode": "open",
        "action": "preferences",
    }
    assert _step_by_id(browser_settings, "open-browser-internal-page").input_preview == {
        "app_name": "Chrome",
        "action": "preferences",
    }

    browser_history = RuntimePlanner().decision(
        "Chrome 打开历史记录",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.ui_elements",
        ],
    )
    assert browser_history.selected_intent.kind == "desktop_operation"
    assert browser_history.selected_intent.inputs["app_name_hint"] == "Chrome"
    assert browser_history.selected_intent.inputs["browser_internal_page_hint"] == {
        "app_name": "Chrome",
        "surface": "history",
        "mode": "focus",
        "action": "show_history",
    }
    assert _step_by_id(browser_history, "open-browser-internal-page").tool_name == (
        "app.focus_and_safe_shortcut"
    )

    assert planner_direct_tool_requests(
        "打开 Chrome 下载内容",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.ui_elements",
            "system.settings_open",
            "desktop.open_path",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "chrome://downloads/"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]
    assert planner_direct_tool_requests(
        "open Chrome downloads",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.open_path",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "chrome://downloads/"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]
    for prompt, shortcut_tool, url in (
        ("Chrome 打开书签", "app.focus_and_safe_shortcut", "chrome://bookmarks/"),
        ("open Chrome extensions", "app.open_and_safe_shortcut", "chrome://extensions/"),
    ):
        assert planner_direct_tool_requests(
            prompt,
            allowed_tools=[
                "desktop.list_apps",
                "app.open_and_safe_shortcut",
                "app.focus_and_safe_shortcut",
                "desktop.safe_type_text",
                "desktop.search_submit",
                "desktop.ui_elements",
            ],
        ) == [
            {
                "protocol": "json_fallback",
                "tool": shortcut_tool,
                "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
                "source": "runtime_planner",
                "planning_reason": "planner_fallback_desktop_operation",
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_type_text",
                "input": {"text": url},
                "source": "runtime_planner",
                "planning_reason": "planner_fallback_desktop_operation",
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.search_submit",
                "input": {},
                "source": "runtime_planner",
                "planning_reason": "planner_fallback_desktop_operation",
            },
        ]
    assert planner_direct_tool_requests(
        "打开 Chrome 设置",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.ui_elements",
            "system.settings_open",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "preferences"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]
    assert planner_direct_tool_requests(
        "Chrome 打开历史记录",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.ui_elements",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "show_history"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]


def test_runtime_planner_routes_app_preferences_without_system_settings() -> None:
    slack_preferences = RuntimePlanner().decision(
        "打开 Slack 偏好设置",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
            "desktop.ui_elements",
            "system.settings_open",
        ],
    )
    assert slack_preferences.selected_intent.kind == "desktop_operation"
    assert slack_preferences.selected_intent.inputs["app_name_hint"] == "Slack"
    assert slack_preferences.selected_intent.inputs["app_preferences_hint"] == {
        "app_name": "Slack",
        "mode": "open",
        "action": "preferences",
    }
    assert _step_by_id(slack_preferences, "open-app-preferences").input_preview == {
        "app_name": "Slack",
        "action": "preferences",
    }

    scoped_preferences = RuntimePlanner().decision(
        "在 Slack 里打开偏好设置",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
            "desktop.ui_elements",
            "system.settings_open",
        ],
    )
    assert scoped_preferences.selected_intent.kind == "desktop_operation"
    assert scoped_preferences.selected_intent.inputs["app_preferences_hint"] == {
        "app_name": "Slack",
        "mode": "focus",
        "action": "preferences",
    }

    english_preferences = RuntimePlanner().decision(
        "Slack preferences",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.ui_elements",
            "system.settings_open",
        ],
    )
    assert english_preferences.selected_intent.kind == "desktop_operation"
    assert english_preferences.selected_intent.inputs["app_preferences_hint"] == {
        "app_name": "Slack",
        "mode": "focus",
        "action": "preferences",
    }

    open_english_preferences = RuntimePlanner().decision(
        "open Slack preferences",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.ui_elements",
            "system.settings_open",
        ],
    )
    assert open_english_preferences.selected_intent.kind == "desktop_operation"
    assert open_english_preferences.selected_intent.inputs["app_preferences_hint"] == {
        "app_name": "Slack",
        "mode": "open",
        "action": "preferences",
    }

    assert planner_direct_tool_requests(
        "打开 Slack 偏好设置",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.ui_elements",
            "system.settings_open",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "preferences"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]
    assert planner_direct_tool_requests(
        "Slack preferences",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.ui_elements",
            "system.settings_open",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "preferences"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]

    bluetooth_settings = RuntimePlanner().decision(
        "打开蓝牙设置",
        allowed_tools=["system.settings_open", "app.open_and_safe_shortcut"],
    )
    assert bluetooth_settings.selected_intent.kind == "system_control"
    assert bluetooth_settings.selected_intent.inputs == {
        "kind": "settings_open",
        "payload": {"target": "蓝牙"},
        "inspect_ui": False,
    }

    sound_settings = RuntimePlanner().decision(
        "open sound settings",
        allowed_tools=["system.settings_open", "app.open_and_safe_shortcut"],
    )
    assert sound_settings.selected_intent.kind == "system_control"
    assert sound_settings.selected_intent.inputs == {
        "kind": "settings_open",
        "payload": {"target": "声音"},
        "inspect_ui": False,
    }

    system_settings = RuntimePlanner().decision(
        "打开系统设置",
        allowed_tools=["system.settings_open", "app.open_and_safe_shortcut"],
    )
    assert system_settings.selected_intent.kind == "system_control"
    assert system_settings.selected_intent.inputs == {
        "kind": "settings_open",
        "payload": {"target": "系统设置"},
        "inspect_ui": False,
    }


def test_runtime_planner_routes_spotlight_search_to_safe_shortcut_sequence() -> None:
    decision = RuntimePlanner().decision(
        "Spotlight 搜索 yachiyo",
        allowed_tools=["desktop.safe_shortcut", "desktop.safe_type_text", "browser.open_url"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["spotlight_search_hint"] == {"query": "yachiyo"}
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "open-spotlight-search",
        "type-spotlight-search-query",
    ]
    assert _step_by_id(decision, "open-spotlight-search").input_preview == {
        "action": "spotlight_search"
    }
    assert _step_by_id(decision, "type-spotlight-search-query").input_preview == {
        "text": "yachiyo"
    }


def test_runtime_planner_keeps_current_app_input_foreground_scoped() -> None:
    decision = RuntimePlanner().decision(
        "在当前应用输入 hello",
        allowed_tools=["desktop.active_window", "desktop.safe_type_text", "desktop.ui_elements"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == ""
    assert _step_by_id(decision, "operate-foreground-ui").tool_name == "desktop.safe_type_text"
    assert _step_by_id(decision, "operate-foreground-ui").input_preview == {"text": "hello"}


def test_runtime_planner_sequences_safe_type_then_followup_shortcut() -> None:
    decision = RuntimePlanner().decision(
        "打开 Notes，输入 hello，再复制",
        allowed_tools=["app.open_and_safe_type_text", "desktop.safe_shortcut"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "operate-foreground-ui",
        "operate-foreground-ui-followup",
        "verify-desktop-result",
    ]
    type_step = _step_by_id(decision, "operate-foreground-ui")
    assert type_step.tool_name == "app.open_and_safe_type_text"
    assert type_step.input_preview == {"app_name": "Notes", "text": "hello"}
    followup = _step_by_id(decision, "operate-foreground-ui-followup")
    assert followup.tool_name == "desktop.safe_shortcut"
    assert followup.input_preview == {"action": "copy"}
    assert followup.depends_on == ["operate-foreground-ui"]
    assert _step_by_id(decision, "verify-desktop-result").depends_on == [
        "operate-foreground-ui-followup"
    ]


def test_runtime_planner_sequences_app_scoped_safe_shortcuts() -> None:
    decision = RuntimePlanner().decision(
        "打开微信然后全选复制",
        allowed_tools=["desktop.list_apps", "app.open_and_safe_shortcut", "desktop.safe_shortcut"],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs == {
        "app_name_hint": "微信",
        "operation_hint": "safe_shortcut_sequence",
        "safe_shortcut_sequence_hint": [{"action": "select_all"}, {"action": "copy"}],
        "safe_shortcut_hint": {"action": "select_all"},
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "discover-desktop-state",
        "operate-foreground-ui",
        "operate-foreground-ui-followup",
        "verify-desktop-result",
    ]
    first = _step_by_id(decision, "operate-foreground-ui")
    assert first.tool_name == "app.open_and_safe_shortcut"
    assert first.input_preview == {"app_name": "微信", "action": "select_all"}
    followup = _step_by_id(decision, "operate-foreground-ui-followup")
    assert followup.tool_name == "desktop.safe_shortcut"
    assert followup.input_preview == {"action": "copy"}
    assert followup.depends_on == ["operate-foreground-ui"]
    assert _step_by_id(decision, "verify-desktop-result").depends_on == [
        "operate-foreground-ui-followup"
    ]


def test_runtime_planner_routes_generic_app_new_document_shortcuts() -> None:
    cases = (
        ("在 Keynote 新建一个演示文稿", "Keynote", "app.focus_and_safe_shortcut"),
        ("用 Pages 新建一份文档", "Pages", "app.focus_and_safe_shortcut"),
        ("在 Numbers 新建一个表格", "Numbers", "app.focus_and_safe_shortcut"),
        ("打开 Keynote 新建演示", "Keynote", "app.open_and_safe_shortcut"),
    )
    allowed_tools = [
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "desktop.safe_shortcut",
        "desktop.ui_elements",
        "data.analyze",
        "artifact.write",
    ]

    for prompt, app_name, expected_tool in cases:
        decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)

        assert decision.selected_intent.kind == "desktop_operation"
        assert decision.selected_intent.inputs == {
            "app_name_hint": app_name,
            "operation_hint": "safe_shortcut",
            "safe_shortcut_hint": {"action": "new_document"},
        }
        discover = _step_by_id(decision, "discover-desktop-state")
        assert discover.tool_name == "desktop.list_apps"
        assert discover.input_preview == {"query": app_name, "limit": 20}
        operate = _step_by_id(decision, "operate-foreground-ui")
        assert operate.tool_name == expected_tool
        assert operate.input_preview == {"app_name": app_name, "action": "new_document"}
        assert _step_by_id(decision, "verify-desktop-result").tool_name == "desktop.ui_elements"

    foreground = RuntimePlanner().decision(
        "新建一个演示文稿",
        allowed_tools=["desktop.safe_shortcut", "desktop.ui_elements"],
    )
    assert foreground.selected_intent.kind == "desktop_operation"
    assert foreground.selected_intent.inputs == {
        "app_name_hint": "",
        "operation_hint": "safe_shortcut",
        "safe_shortcut_hint": {"action": "new_document"},
    }
    assert _step_by_id(foreground, "operate-foreground-ui").input_preview == {
        "action": "new_document"
    }


def test_runtime_planner_verifies_followup_ui_operations_with_ui_read_first() -> None:
    decision = RuntimePlanner().decision(
        "打开 Notes，输入 hello，再复制",
        allowed_tools=[
            "desktop.active_window",
            "app.open_and_safe_type_text",
            "desktop.safe_shortcut",
            "desktop.ui_elements",
        ],
    )

    verify = _step_by_id(decision, "verify-desktop-result")
    assert verify.tool_name == "desktop.ui_elements"
    assert verify.action == "read_ui"
    assert verify.depends_on == ["operate-foreground-ui-followup"]


def test_runtime_planner_routes_safe_key_scroll_and_click_without_approval() -> None:
    key_decision = RuntimePlanner().decision(
        "按下一页键",
        allowed_tools=["desktop.active_window", "desktop.safe_key"],
    )
    scroll_decision = RuntimePlanner().decision(
        "向下滚动两页",
        allowed_tools=["desktop.active_window", "desktop.safe_scroll"],
    )
    click_decision = RuntimePlanner().decision(
        "点击坐标 120, 240",
        allowed_tools=["desktop.active_window", "desktop.safe_click"],
    )

    key_step = _step_by_id(key_decision, "operate-foreground-ui")
    assert key_decision.selected_intent.inputs["operation_hint"] == "safe_key"
    assert key_decision.selected_intent.inputs["safe_key_hint"] == {
        "action": "page_down",
        "repeat_count": 1,
    }
    assert key_step.tool_name == "desktop.safe_key"
    assert key_step.input_preview == {"action": "page_down", "repeat_count": 1}
    assert key_step.risk_level == "low"
    assert key_step.approval_required is False

    show_desktop_decision = RuntimePlanner().decision(
        "show desktop",
        allowed_tools=["desktop.active_window", "desktop.safe_key"],
    )
    assert show_desktop_decision.selected_intent.inputs == {
        "app_name_hint": "",
        "operation_hint": "safe_key",
        "safe_key_hint": {"action": "show_desktop", "repeat_count": 1},
    }
    assert _step_by_id(show_desktop_decision, "operate-foreground-ui").input_preview == {
        "action": "show_desktop",
        "repeat_count": 1,
    }

    scroll_step = _step_by_id(scroll_decision, "operate-foreground-ui")
    assert scroll_decision.selected_intent.inputs["operation_hint"] == "safe_scroll"
    assert scroll_decision.selected_intent.inputs["safe_scroll_hint"] == {
        "direction": "down",
        "pages": 2,
    }
    assert scroll_step.tool_name == "desktop.safe_scroll"
    assert scroll_step.input_preview == {"direction": "down", "pages": 2}
    assert scroll_step.risk_level == "low"
    assert scroll_step.approval_required is False

    app_key_decision = RuntimePlanner().decision(
        "打开 Slack 按下箭头三次",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_key",
            "desktop.ui_elements",
        ],
    )
    assert app_key_decision.selected_intent.inputs["app_name_hint"] == "Slack"
    assert app_key_decision.selected_intent.inputs["operation_hint"] == "safe_key"
    assert app_key_decision.selected_intent.inputs["safe_key_hint"] == {
        "action": "arrow_down",
        "repeat_count": 3,
    }
    app_key_step = _step_by_id(app_key_decision, "operate-foreground-ui")
    assert app_key_step.tool_name == "app.open_and_safe_key"
    assert app_key_step.input_preview == {
        "app_name": "Slack",
        "action": "arrow_down",
        "repeat_count": 3,
    }

    app_scroll_decision = RuntimePlanner().decision(
        "切到 Slack 向下滚动两页",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_safe_scroll",
            "desktop.ui_elements",
        ],
    )
    assert app_scroll_decision.selected_intent.inputs["app_name_hint"] == "Slack"
    assert app_scroll_decision.selected_intent.inputs["operation_hint"] == "safe_scroll"
    assert app_scroll_decision.selected_intent.inputs["safe_scroll_hint"] == {
        "direction": "down",
        "pages": 2,
    }
    app_scroll_step = _step_by_id(app_scroll_decision, "operate-foreground-ui")
    assert app_scroll_step.tool_name == "app.focus_and_safe_scroll"
    assert app_scroll_step.input_preview == {
        "app_name": "Slack",
        "direction": "down",
        "pages": 2,
    }

    app_shortcut_decision = RuntimePlanner().decision(
        "切到 Chrome 后退一下",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.ui_elements",
        ],
    )
    assert app_shortcut_decision.selected_intent.inputs["app_name_hint"] == "Chrome"
    assert app_shortcut_decision.selected_intent.inputs["operation_hint"] == "safe_shortcut"
    assert app_shortcut_decision.selected_intent.inputs["safe_shortcut_hint"] == {
        "action": "browser_back"
    }
    app_shortcut_step = _step_by_id(app_shortcut_decision, "operate-foreground-ui")
    assert app_shortcut_step.tool_name == "app.focus_and_safe_shortcut"
    assert app_shortcut_step.input_preview == {
        "app_name": "Chrome",
        "action": "browser_back",
    }

    click_step = _step_by_id(click_decision, "operate-foreground-ui")
    assert click_decision.selected_intent.inputs["operation_hint"] == "safe_click"
    assert click_decision.selected_intent.inputs["safe_click_hint"] == {
        "x": 120,
        "y": 240,
    }
    assert click_step.tool_name == "desktop.safe_click"
    assert click_step.input_preview == {"x": 120, "y": 240}
    assert click_step.risk_level == "low"
    assert click_step.approval_required is False


def test_planner_direct_tool_requests_maps_app_scoped_safe_operations() -> None:
    assert planner_direct_tool_requests(
        "打开 Slack 按下箭头三次",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_key",
            "desktop.ui_elements",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_key",
            "input": {"app_name": "Slack", "action": "arrow_down", "repeat_count": 3},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]

    assert planner_direct_tool_requests(
        "切到 Slack 向下滚动两页",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_safe_scroll",
            "desktop.ui_elements",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_scroll",
            "input": {"app_name": "Slack", "direction": "down", "pages": 2},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]

    assert planner_direct_tool_requests(
        "打开 Chrome 然后按 Tab",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_key",
            "desktop.ui_elements",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_key",
            "input": {"app_name": "Google Chrome", "action": "tab", "repeat_count": 1},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]

    for prompt, tool_name, payload in (
        (
            "切到 Chrome 后退一下",
            "app.focus_and_safe_shortcut",
            {"app_name": "Google Chrome", "action": "browser_back"},
        ),
        (
            "打开 Slack 并复制",
            "app.open_and_safe_shortcut",
            {"app_name": "Slack", "action": "copy"},
        ),
        (
            "打开 Chrome 开发者工具",
            "app.open_and_safe_shortcut",
            {"app_name": "Google Chrome", "action": "open_devtools"},
        ),
        (
            "Chrome 新建标签页",
            "app.focus_and_safe_shortcut",
            {"app_name": "Google Chrome", "action": "new_tab"},
        ),
    ):
        assert planner_direct_tool_requests(
            prompt,
            allowed_tools=[
                "desktop.list_apps",
                "app.open_and_safe_shortcut",
                "app.focus_and_safe_shortcut",
                "desktop.ui_elements",
            ],
        ) == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": payload,
                "source": "runtime_planner",
                "planning_reason": "planner_fallback_desktop_operation",
            }
        ]


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
    cases = (
        ("可以帮我打开 Word 吗", "Word"),
        ("open Raycast app please?", "Raycast"),
        ("launch SuperData Studio application", "SuperData Studio"),
        ("打开微信应用", "微信"),
        ("启动 Obsidian 软件", "Obsidian"),
    )

    for prompt, expected_app_name in cases:
        decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=["desktop.running_apps", "app.open", "desktop.active_window"],
        )

        assert decision.selected_intent.kind == "desktop_operation"
        assert decision.selected_intent.inputs["app_name_hint"] == expected_app_name
        assert _step_by_id(decision, "open-or-focus-app").input_preview == {
            "app_name": expected_app_name,
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


def test_runtime_planner_routes_pure_foreground_submit_to_approval_gate() -> None:
    for prompt, action in (
        ("按回车提交", "submit"),
        ("当前输入框发送", "send"),
        ("前台发送", "send"),
        ("发送前台内容", "send"),
    ):
        decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=[
                "desktop.running_apps",
                "desktop.submit_foreground",
                "desktop.active_window",
            ],
        )

        assert decision.selected_intent.kind == "desktop_operation"
        assert decision.selected_intent.inputs["operation_hint"] == "submit_foreground"
        submit = _step_by_id(decision, "submit-foreground-ui")
        assert submit.tool_name == "desktop.submit_foreground"
        assert submit.input_preview == {"action": action}
        assert submit.risk_level == "high"
        assert submit.approval_required is True
        assert submit.depends_on == ["discover-desktop-state"]


def test_runtime_planner_focuses_app_before_foreground_submit() -> None:
    decision = RuntimePlanner().decision(
        "微信按回车发送",
        allowed_tools=[
            "desktop.running_apps",
            "app.focus",
            "desktop.submit_foreground",
            "desktop.active_window",
        ],
    )
    generic_app_decision = RuntimePlanner().decision(
        "Slack 回车发送",
        allowed_tools=[
            "desktop.running_apps",
            "app.focus",
            "desktop.submit_foreground",
            "desktop.active_window",
        ],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs["app_name_hint"] == "WeChat"
    focus = _step_by_id(decision, "open-or-focus-app")
    assert focus.tool_name == "app.focus"
    assert focus.input_preview == {"app_name": "WeChat"}
    submit = _step_by_id(decision, "submit-foreground-ui")
    assert submit.tool_name == "desktop.submit_foreground"
    assert submit.input_preview == {"action": "send"}
    assert submit.depends_on == ["open-or-focus-app"]
    assert generic_app_decision.selected_intent.inputs["app_name_hint"] == "Slack"
    generic_focus = _step_by_id(generic_app_decision, "open-or-focus-app")
    assert generic_focus.tool_name == "app.focus"
    assert generic_focus.input_preview == {"app_name": "Slack"}
    assert _step_by_id(generic_app_decision, "submit-foreground-ui").input_preview == {
        "action": "send"
    }


def test_runtime_planner_keeps_plain_current_window_enter_as_hotkey() -> None:
    decision = RuntimePlanner().decision(
        "当前窗口按回车",
        allowed_tools=[
            "desktop.running_apps",
            "desktop.hotkey",
            "desktop.submit_foreground",
        ],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert "foreground_submit_action_hint" not in decision.selected_intent.inputs
    hotkey = _step_by_id(decision, "operate-foreground-ui")
    assert hotkey.tool_name == "desktop.hotkey"
    assert hotkey.input_preview == {"key": "return", "modifiers": []}


def test_runtime_planner_routes_app_scoped_compose_then_send() -> None:
    focus = planner_direct_tool_requests(
        "微信输入 hello 并发送",
        [
            "app.focus_and_safe_type_text",
            "desktop.safe_type_text",
            "desktop.submit_foreground",
        ],
    )
    open_app = planner_direct_tool_requests(
        "打开微信发送 hello",
        [
            "app.open_and_safe_type_text",
            "desktop.safe_type_text",
            "desktop.submit_foreground",
        ],
    )
    generic_open_app = planner_direct_tool_requests(
        "打开 Obsidian 写 hello",
        [
            "desktop.list_apps",
            "app.open_and_safe_type_text",
            "desktop.safe_type_text",
            "desktop.ui_elements",
        ],
    )
    generic_focus_app = planner_direct_tool_requests(
        "在 Notes 输入 hello",
        [
            "desktop.list_apps",
            "app.focus_and_safe_type_text",
            "app.open_and_safe_type_text",
            "desktop.safe_type_text",
            "desktop.ui_elements",
        ],
    )

    assert focus == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_type_text",
            "input": {"app_name": "WeChat", "text": "hello"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]
    assert open_app == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_type_text",
            "input": {"app_name": "WeChat", "text": "hello"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]
    assert generic_open_app == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_type_text",
            "input": {"app_name": "Obsidian", "text": "hello"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]
    assert generic_focus_app == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_type_text",
            "input": {"app_name": "Notes", "text": "hello"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]


def test_runtime_planner_routes_paste_then_send() -> None:
    foreground = planner_direct_tool_requests(
        "当前输入框粘贴并发送",
        [
            "desktop.safe_shortcut",
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
            "desktop.submit_foreground",
        ],
    )
    open_app = planner_direct_tool_requests(
        "打开微信粘贴后发送",
        [
            "desktop.safe_shortcut",
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
            "desktop.submit_foreground",
        ],
    )

    assert foreground == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]
    assert open_app == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
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


def test_runtime_planner_routes_app_scoped_fullscreen_shortcut_to_desktop_operation() -> None:
    decision = RuntimePlanner().decision(
        "Chrome 最大化",
        allowed_tools=[
            "system.volume",
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.safe_shortcut",
        ],
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert decision.selected_intent.inputs == {
        "app_name_hint": "Chrome",
        "operation_hint": "safe_shortcut",
        "safe_shortcut_hint": {"action": "toggle_full_screen"},
    }
    discover = _step_by_id(decision, "discover-desktop-state")
    assert discover.tool_name == "desktop.list_apps"
    assert discover.input_preview == {"query": "Chrome", "limit": 20}
    operate = _step_by_id(decision, "operate-foreground-ui")
    assert operate.tool_name == "app.focus_and_safe_shortcut"
    assert operate.input_preview == {"app_name": "Chrome", "action": "toggle_full_screen"}
    assert all(step.tool_name != "system.volume" for step in decision.plan.tool_plan.steps)


def test_runtime_planner_routes_finder_scoped_safe_shortcuts() -> None:
    cases = (
        ("打开Finder然后按空格", "app.open_and_safe_shortcut", "finder_quick_look"),
        ("Finder按空格", "app.focus_and_safe_shortcut", "finder_quick_look"),
        ("打开 Finder 新建文件夹", "app.open_and_safe_shortcut", "new_folder"),
        ("Finder 新建文件夹", "app.focus_and_safe_shortcut", "new_folder"),
        ("打开 Finder 重命名选中文件", "app.open_and_safe_shortcut", "rename_selected"),
        ("Finder 上一级目录", "app.focus_and_safe_shortcut", "parent_folder"),
        ("在 Finder 里显示简介", "app.focus_and_safe_shortcut", "finder_get_info"),
        ("Finder 复制选中文件", "app.focus_and_safe_shortcut", "copy"),
    )
    allowed_tools = [
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "desktop.safe_shortcut",
    ]

    for prompt, expected_tool, expected_action in cases:
        decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)

        assert decision.selected_intent.kind == "desktop_operation"
        assert decision.selected_intent.inputs == {
            "app_name_hint": "Finder",
            "operation_hint": "safe_shortcut",
            "safe_shortcut_hint": {"action": expected_action},
        }
        operate = _step_by_id(decision, "operate-foreground-ui")
        assert operate.tool_name == expected_tool
        assert operate.input_preview == {"app_name": "Finder", "action": expected_action}
        assert operate.approval_required is False

    chrome = RuntimePlanner().decision(
        "Chrome 新建文件夹",
        allowed_tools=allowed_tools,
    )
    bare = RuntimePlanner().decision(
        "新建文件夹",
        allowed_tools=allowed_tools,
    )
    assert chrome.selected_intent.kind == "general"
    assert bare.selected_intent.kind == "general"


def test_runtime_planner_routes_media_playback_to_media_capability() -> None:
    for prompt in (
        "能否帮我播放 Apple Music?",
        "能不能直接播个 Apple Music",
        "can you play some music?",
    ):
        decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=["media.apple_music_open_and_play"],
        )

        assert decision.selected_intent.kind == "media_playback"
        assert decision.selected_intent.inputs["action"] == "play"
        assert decision.selected_intent.inputs["query"] == ""
        step = _step_by_id(decision, "control-media-playback")
        assert step.tool_name == "media.apple_music_open_and_play"
        assert step.input_preview == {}
        media_capability = _capability_by_id(decision, "media.playback")
        assert "media.apple_music_open_and_play" in media_capability.tools


def test_runtime_planner_routes_media_query_to_apple_music_search_play() -> None:
    for prompt, query in (
        ("播放超时空辉夜姬", "超时空辉夜姬"),
        ("放点周杰伦", "周杰伦"),
        ("播点轻音乐", "轻音乐"),
        ("play some jazz", "jazz"),
        ("play Some Nights", "Some Nights"),
        ("put some jazz on Apple Music", "jazz"),
        ("search Apple Music for Taylor Swift and play it", "Taylor Swift"),
        ("search Space Oddity in Apple Music and play it", "Space Oddity"),
        ("Apple Music search Space Oddity and play it", "Space Oddity"),
        ("帮我在 Apple Music 搜一下超时空辉夜姬并播放", "超时空辉夜姬"),
        ("打开 Apple Music 搜索超时空辉夜姬并播放", "超时空辉夜姬"),
        ("超时空辉夜姬播放", "超时空辉夜姬"),
        ("周杰伦播放一下", "周杰伦"),
    ):
        decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=["media.apple_music_play"],
        )

        assert decision.selected_intent.kind == "media_playback"
        assert decision.selected_intent.inputs["query"] == query
        step = _step_by_id(decision, "control-media-playback")
        assert step.tool_name == "media.apple_music_play"
        assert step.input_preview == {"query": query}


def test_runtime_planner_routes_media_status_to_readonly_tool() -> None:
    for prompt in (
        "查看当前 Apple Music 播放状态",
        "Apple Music 播放进度",
        "Apple Music 在播状态",
    ):
        decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=["media.apple_music_status", "media.apple_music_play"],
        )

        assert decision.selected_intent.kind == "media_playback"
        assert decision.selected_intent.inputs["action"] == "status"
        assert decision.selected_intent.inputs["query"] == ""
        step = _step_by_id(decision, "control-media-playback")
        assert step.tool_name == "media.apple_music_status"
        assert step.input_preview == {}


def test_runtime_planner_routes_named_music_app_query_through_app_search() -> None:
    decision = RuntimePlanner().decision(
        "在 Spotify 播放 lo-fi",
        allowed_tools=[
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "media.music_app_open_and_play",
        ],
    )

    assert decision.selected_intent.kind == "media_playback"
    assert decision.selected_intent.inputs == {
        "action": "play",
        "app_name": "Spotify",
        "query": "lo-fi",
        "control_only": "",
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "focus-media-app-search",
        "type-media-search-query",
        "submit-media-search",
    ]
    assert _step_by_id(decision, "focus-media-app-search").tool_name == (
        "app.open_and_safe_shortcut"
    )
    assert _step_by_id(decision, "focus-media-app-search").input_preview == {
        "app_name": "Spotify",
        "action": "find",
    }
    assert _step_by_id(decision, "type-media-search-query").input_preview == {
        "text": "lo-fi"
    }
    assert _step_by_id(decision, "submit-media-search").tool_name == "desktop.search_submit"


def test_runtime_planner_routes_natural_media_controls_to_media_tools() -> None:
    cases = (
        ("切歌", "next"),
        ("跳过这首", "next"),
        ("别放了", "pause"),
    )
    for prompt, action in cases:
        decision = RuntimePlanner().decision(
            prompt,
            allowed_tools=["media.system_control", "desktop.running_apps"],
            metadata={"daily_desktop_intent": True},
        )

        assert decision.selected_intent.kind == "media_playback"
        assert decision.selected_intent.inputs["action"] == action
        step = _step_by_id(decision, "control-media-playback")
        assert step.tool_name == "media.system_control"
        assert step.input_preview == {"action": action}


def test_runtime_planner_routes_system_volume_to_system_control() -> None:
    decision = RuntimePlanner().decision(
        "把系统音量调到 50%",
        allowed_tools=["system.volume"],
    )
    max_volume = RuntimePlanner().decision(
        "把音量调到最大",
        allowed_tools=["system.volume"],
    )
    louder = RuntimePlanner().decision(
        "大点声",
        allowed_tools=["system.volume"],
    )
    quieter = RuntimePlanner().decision(
        "声音小一点",
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
    assert max_volume.selected_intent.kind == "system_control"
    assert max_volume.selected_intent.inputs == {
        "kind": "volume",
        "payload": {"action": "set", "level": 100},
    }
    assert louder.selected_intent.kind == "system_control"
    assert louder.selected_intent.inputs == {
        "kind": "volume",
        "payload": {"action": "up"},
    }
    assert _step_by_id(louder, "control-system-state").tool_name == "system.volume"
    assert quieter.selected_intent.kind == "system_control"
    assert quieter.selected_intent.inputs == {
        "kind": "volume",
        "payload": {"action": "down"},
    }


def test_runtime_planner_routes_brightness_and_display_controls() -> None:
    brightness = RuntimePlanner().decision(
        "屏幕太亮了，调暗一点",
        allowed_tools=["system.brightness"],
    )
    display_sleep = RuntimePlanner().decision(
        "关闭屏幕",
        allowed_tools=["system.display_sleep"],
    )
    screen_saver = RuntimePlanner().decision(
        "启动屏幕保护程序",
        allowed_tools=["system.settings_open", "system.screen_saver_start"],
    )

    assert brightness.selected_intent.kind == "system_control"
    assert _step_by_id(brightness, "control-system-state").tool_name == "system.brightness"
    assert _step_by_id(brightness, "control-system-state").input_preview == {
        "action": "down",
        "step": 2,
    }
    assert display_sleep.selected_intent.kind == "system_control"
    assert _step_by_id(display_sleep, "control-system-state").tool_name == "system.display_sleep"
    assert screen_saver.selected_intent.kind == "system_control"
    assert screen_saver.selected_intent.inputs == {"kind": "screen_saver", "payload": {}}
    assert _step_by_id(screen_saver, "control-system-state").tool_name == "system.screen_saver_start"


def test_runtime_planner_routes_system_settings_open_to_system_control() -> None:
    decision = RuntimePlanner().decision(
        "打开蓝牙",
        allowed_tools=["system.settings_open", "desktop.ui_elements"],
    )
    screen_saver_settings = RuntimePlanner().decision(
        "打开屏幕保护程序设置",
        allowed_tools=["system.settings_open", "system.screen_saver_start"],
    )

    assert decision.selected_intent.kind == "system_control"
    assert decision.selected_intent.inputs == {
        "kind": "settings_open",
        "payload": {"target": "蓝牙"},
        "inspect_ui": False,
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "open-system-settings"
    ]
    step = _step_by_id(decision, "open-system-settings")
    assert step.capability_id == "system.control"
    assert step.tool_name == "system.settings_open"
    assert step.action == "open_settings"
    assert step.input_preview == {"target": "蓝牙"}
    assert screen_saver_settings.selected_intent.kind == "system_control"
    assert screen_saver_settings.selected_intent.inputs == {
        "kind": "settings_open",
        "payload": {"target": "屏幕保护程序"},
        "inspect_ui": False,
    }
    assert (
        _step_by_id(screen_saver_settings, "open-system-settings").tool_name
        == "system.settings_open"
    )

    inspect = RuntimePlanner().decision(
        "打开系统设置看看有哪些选项",
        allowed_tools=["system.settings_open", "desktop.ui_elements"],
    )
    assert inspect.selected_intent.kind == "system_control"
    assert inspect.selected_intent.inputs == {
        "kind": "settings_open",
        "payload": {"target": "系统设置"},
        "inspect_ui": True,
    }
    assert [step.step_id for step in inspect.plan.tool_plan.steps] == [
        "open-system-settings",
        "read-system-settings-ui",
    ]
    assert _step_by_id(inspect, "read-system-settings-ui").tool_name == "desktop.ui_elements"
    assert _step_by_id(inspect, "read-system-settings-ui").depends_on == [
        "open-system-settings"
    ]


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


def test_runtime_planner_routes_direct_communication_send_sequence() -> None:
    decision = RuntimePlanner().decision(
        "打开 Slack 发消息给 yachiyo：hello",
        allowed_tools=[
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
        ],
    )

    assert decision.selected_intent.kind == "communication"
    assert decision.selected_intent.inputs == {
        "direct_message_hint": {
            "app_name": "Slack",
            "recipient": "yachiyo",
            "body": "hello",
            "mode": "open",
            "send_action": "send",
        }
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "focus-communication-recipient-search",
        "type-communication-recipient",
        "submit-communication-recipient-search",
        "draft-communication-message",
        "send-communication-message",
    ]
    assert _step_by_id(decision, "focus-communication-recipient-search").tool_name == (
        "app.open_and_safe_shortcut"
    )
    assert _step_by_id(decision, "type-communication-recipient").input_preview == {
        "text": "yachiyo"
    }
    assert _step_by_id(decision, "draft-communication-message").input_preview == {
        "text": "hello"
    }
    send_step = _step_by_id(decision, "send-communication-message")
    assert send_step.tool_name == "desktop.submit_foreground"
    assert send_step.input_preview == {"action": "send"}
    assert send_step.approval_required is True
    assert send_step.risk_level == "high"


def test_runtime_planner_routes_implicit_chinese_direct_communication_send_sequence() -> None:
    requests = planner_direct_tool_requests(
        "打开微信发消息给张三你好",
        [
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
        ],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "张三"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "你好"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
    ]


def test_runtime_planner_routes_app_recipient_body_communication_sequence() -> None:
    allowed_tools = [
        "app.focus_and_safe_shortcut",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.submit_foreground",
    ]

    decision = RuntimePlanner().decision(
        "用微信给文件传输助手发送你好",
        allowed_tools=allowed_tools,
    )

    assert decision.selected_intent.kind == "communication"
    assert decision.selected_intent.inputs == {
        "direct_message_hint": {
            "app_name": "WeChat",
            "recipient": "文件传输助手",
            "body": "你好",
            "mode": "focus",
            "send_action": "send",
        }
    }
    assert planner_direct_tool_requests("用微信给文件传输助手发送你好", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "你好"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
    ]

    open_decision = RuntimePlanner().decision(
        "打开微信给文件传输助手发送你好",
        allowed_tools=allowed_tools,
    )

    assert open_decision.selected_intent.kind == "communication"
    assert open_decision.selected_intent.inputs["direct_message_hint"] == {
        "app_name": "WeChat",
        "recipient": "文件传输助手",
        "body": "你好",
        "mode": "open",
        "send_action": "send",
    }
    assert _step_by_id(open_decision, "focus-communication-recipient-search").tool_name == (
        "app.open_and_safe_shortcut"
    )


def test_runtime_planner_routes_flexible_communication_surface_phrasing() -> None:
    allowed_tools = [
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.submit_foreground",
    ]
    examples = [
        (
            "帮我在微信给文件传输助手说测试一下",
            {
                "app_name": "WeChat",
                "recipient": "文件传输助手",
                "body": "测试一下",
                "mode": "focus",
                "send_action": "send",
            },
        ),
        (
            "send hello in Slack to yachiyo",
            {
                "app_name": "Slack",
                "recipient": "yachiyo",
                "body": "hello",
                "mode": "focus",
                "send_action": "send",
            },
        ),
        (
            "message yachiyo in Slack hello",
            {
                "app_name": "Slack",
                "recipient": "yachiyo",
                "body": "hello",
                "mode": "focus",
                "send_action": "send",
            },
        ),
        (
            "发微信给张三：你好",
            {
                "app_name": "WeChat",
                "recipient": "张三",
                "body": "你好",
                "mode": "focus",
                "send_action": "send",
            },
        ),
        (
            "给张三发微信：你好",
            {
                "app_name": "WeChat",
                "recipient": "张三",
                "body": "你好",
                "mode": "focus",
                "send_action": "send",
            },
        ),
    ]

    for prompt, direct_hint in examples:
        decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)

        assert decision.selected_intent.kind == "communication"
        assert decision.selected_intent.inputs == {"direct_message_hint": direct_hint}

    generic_decision = RuntimePlanner().decision(
        "发送消息给 Alice：今晚八点见",
        allowed_tools=allowed_tools,
    )
    assert generic_decision.selected_intent.kind == "communication"
    assert generic_decision.selected_intent.inputs == {}


def test_runtime_planner_routes_direct_context_communication_send_sequence() -> None:
    decision = RuntimePlanner().decision(
        "send selected text in Slack to yachiyo",
        allowed_tools=[
            "app.focus_and_safe_shortcut",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
        ],
    )

    assert decision.selected_intent.kind == "communication"
    assert decision.selected_intent.inputs == {
        "context_source": "selection",
        "direct_message_hint": {
            "app_name": "Slack",
            "recipient": "yachiyo",
            "body_source": "selection",
            "mode": "focus",
            "send_action": "send",
        },
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "copy-communication-body-source",
        "focus-communication-recipient-search",
        "type-communication-recipient",
        "submit-communication-recipient-search",
        "paste-communication-message",
        "send-communication-message",
    ]
    assert _step_by_id(decision, "copy-communication-body-source").input_preview == {
        "action": "copy"
    }
    focus_step = _step_by_id(decision, "focus-communication-recipient-search")
    assert focus_step.tool_name == "app.focus_and_safe_shortcut"
    assert focus_step.input_preview == {"app_name": "Slack", "action": "find"}
    assert focus_step.depends_on == ["copy-communication-body-source"]
    assert _step_by_id(decision, "type-communication-recipient").input_preview == {
        "text": "yachiyo"
    }
    assert _step_by_id(decision, "paste-communication-message").input_preview == {
        "action": "paste"
    }
    send_step = _step_by_id(decision, "send-communication-message")
    assert send_step.tool_name == "desktop.submit_foreground"
    assert send_step.depends_on == ["paste-communication-message"]
    assert send_step.approval_required is True
    assert send_step.risk_level == "high"


def test_runtime_planner_cleans_app_prefix_for_context_communication() -> None:
    decision = RuntimePlanner().decision(
        "用微信给文件传输助手发送剪贴板内容",
        allowed_tools=[
            "app.focus_and_safe_shortcut",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
        ],
    )

    assert decision.selected_intent.kind == "communication"
    assert decision.selected_intent.inputs == {
        "context_source": "clipboard",
        "direct_message_hint": {
            "app_name": "WeChat",
            "recipient": "文件传输助手",
            "body_source": "clipboard",
            "mode": "focus",
            "send_action": "send",
        },
    }
    assert _step_by_id(decision, "focus-communication-recipient-search").input_preview == {
        "app_name": "WeChat",
        "action": "find",
    }


def test_runtime_planner_routes_paste_to_recipient_as_communication() -> None:
    allowed_tools = [
        "app.focus_and_safe_shortcut",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.submit_foreground",
    ]
    decision = RuntimePlanner().decision(
        "微信给文件传输助手粘贴并发送",
        allowed_tools=allowed_tools,
    )

    assert decision.selected_intent.kind == "communication"
    assert decision.selected_intent.inputs == {
        "direct_message_hint": {
            "app_name": "WeChat",
            "recipient": "文件传输助手",
            "body_source": "clipboard",
            "mode": "focus",
            "send_action": "send",
        }
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "focus-communication-recipient-search",
        "type-communication-recipient",
        "submit-communication-recipient-search",
        "paste-communication-message",
        "send-communication-message",
    ]
    assert _step_by_id(decision, "focus-communication-recipient-search").input_preview == {
        "app_name": "WeChat",
        "action": "find",
    }
    assert _step_by_id(decision, "type-communication-recipient").input_preview == {
        "text": "文件传输助手"
    }
    assert _step_by_id(decision, "paste-communication-message").input_preview == {
        "action": "paste"
    }
    send_step = _step_by_id(decision, "send-communication-message")
    assert send_step.input_preview == {"action": "send"}
    assert send_step.approval_required is True
    assert planner_direct_tool_requests("微信给文件传输助手粘贴并发送", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
    ]
    open_decision = RuntimePlanner().decision(
        "打开微信给文件传输助手粘贴并发送",
        allowed_tools=allowed_tools,
    )
    assert open_decision.selected_intent.kind == "communication"
    assert open_decision.selected_intent.inputs["direct_message_hint"] == {
        "app_name": "WeChat",
        "recipient": "文件传输助手",
        "body_source": "clipboard",
        "mode": "open",
        "send_action": "send",
    }


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


def test_runtime_planner_tracks_context_communication_source_without_body() -> None:
    decision = RuntimePlanner().decision(
        "把当前网页内容发给微信文件传输助手",
        allowed_tools=["browser.extract_text", "artifact.write"],
    )

    assert decision.selected_intent.kind == "communication"
    assert decision.selected_intent.inputs == {"context_source": "current_page_content"}
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "read-communication-context",
        "draft-communication-from-context",
    ]
    read_step = _step_by_id(decision, "read-communication-context")
    assert read_step.capability_id == "communication.compose"
    assert read_step.tool_name == "browser.extract_text"
    assert read_step.action == "extract_text"
    draft_step = _step_by_id(decision, "draft-communication-from-context")
    assert draft_step.tool_name == "artifact.write"
    assert draft_step.input_preview == {"body_source": "current_page_content"}
    assert draft_step.depends_on == ["read-communication-context"]
    assert draft_step.approval_required is True


def test_runtime_planner_routes_explicit_note_to_information_capture() -> None:
    decision = RuntimePlanner().decision(
        "新建备忘录内容是 今天要买牛奶",
        allowed_tools=["notes.create"],
    )

    assert decision.selected_intent.kind == "information_capture"
    assert decision.selected_intent.inputs == {
        "action": "create_note",
        "body": "今天要买牛奶",
    }
    assert decision.plan.tool_plan.missing_capabilities == []
    assert decision.plan.tool_plan.artifacts_expected == []
    step = _step_by_id(decision, "create-note")
    assert step.capability_id == "information.capture"
    assert step.action == "create_note"
    assert step.tool_name == "notes.create"
    assert step.input_preview == {"body": "今天要买牛奶"}
    capability = _capability_by_id(decision, "information.capture")
    assert "notes.create" in capability.available_tools


def test_runtime_planner_extracts_common_note_body_forms() -> None:
    examples = (
        ("备忘录记一下今天要买牛奶", "今天要买牛奶"),
        ("把这段文字记到备忘录：今天买牛奶", "今天买牛奶"),
        ("将这个想法记录到笔记：做一个桌面 agent", "做一个桌面 agent"),
        ("把今天买牛奶记到备忘录", "今天买牛奶"),
        ("在 Notes 新建笔记 hello", "hello"),
        ("用备忘录记录一下 hello", "hello"),
        ("create a note in Notes: hello", "hello"),
        ("write note in Notes hello", "hello"),
        ("记一下：hello", "hello"),
        ("make a note to buy milk", "buy milk"),
    )

    for prompt, body in examples:
        decision = RuntimePlanner().decision(prompt, allowed_tools=["notes.create"])

        assert decision.selected_intent.kind == "information_capture"
        assert decision.selected_intent.inputs == {
            "action": "create_note",
            "body": body,
        }
        assert _step_by_id(decision, "create-note").input_preview == {"body": body}


def test_runtime_planner_tracks_context_note_source_without_body() -> None:
    decision = RuntimePlanner().decision(
        "create a note from selected text",
        allowed_tools=["notes.create", "desktop.safe_shortcut", "clipboard.read"],
    )

    assert decision.selected_intent.kind == "information_capture"
    assert decision.selected_intent.inputs == {
        "action": "create_note_from_context",
        "source": "selection",
    }
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "copy-selected-note-context",
        "read-note-context",
        "create-note-from-context",
    ]
    assert _step_by_id(decision, "copy-selected-note-context").input_preview == {
        "action": "copy"
    }
    assert _step_by_id(decision, "read-note-context").tool_name == "clipboard.read"
    create_step = _step_by_id(decision, "create-note-from-context")
    assert create_step.tool_name == "notes.create"
    assert create_step.input_preview == {"body_source": "selection"}
    assert create_step.depends_on == [
        "copy-selected-note-context",
        "read-note-context",
    ]


def test_runtime_planner_tracks_context_schedule_source_without_body() -> None:
    decision = RuntimePlanner().decision(
        "create a reminder from selected text",
        allowed_tools=["reminders.create", "desktop.safe_shortcut", "clipboard.read"],
    )

    assert decision.selected_intent.kind == "schedule"
    assert decision.selected_intent.inputs == {"context_source": "selection"}
    assert [step.step_id for step in decision.plan.tool_plan.steps] == [
        "copy-selected-schedule-context",
        "read-schedule-context",
        "create-schedule-item-from-context",
    ]
    assert _step_by_id(decision, "copy-selected-schedule-context").input_preview == {
        "action": "copy"
    }
    read_step = _step_by_id(decision, "read-schedule-context")
    assert read_step.tool_name == "clipboard.read"
    assert read_step.action == "read_clipboard"
    create_step = _step_by_id(decision, "create-schedule-item-from-context")
    assert create_step.tool_name == "reminders.create"
    assert create_step.input_preview == {"body_source": "selection"}
    assert create_step.approval_required is True


def test_runtime_planner_tracks_browser_context_sources() -> None:
    note_decision = RuntimePlanner().decision(
        "create a note from current page link",
        allowed_tools=["notes.create", "browser.current_page"],
    )
    assert note_decision.selected_intent.kind == "information_capture"
    note_read_step = _step_by_id(note_decision, "read-note-context")
    assert note_read_step.tool_name == "browser.current_page"
    assert note_read_step.action == "read_current_page"

    schedule_decision = RuntimePlanner().decision(
        "把当前页面内容创建成日历事件",
        allowed_tools=["calendar.create_event", "browser.extract_text"],
    )
    assert schedule_decision.selected_intent.kind == "schedule"
    schedule_read_step = _step_by_id(schedule_decision, "read-schedule-context")
    assert schedule_read_step.tool_name == "browser.extract_text"
    assert schedule_read_step.action == "extract_text"


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


def test_capability_registry_exposes_foreground_management_tools() -> None:
    snapshots = capability_snapshots(
        allowed_tools=["desktop.minimize_window", "desktop.close_window", "desktop.quit_app"],
        capability_ids=["desktop.app_control"],
    )

    assert snapshots[0].available_tools == [
        "desktop.minimize_window",
        "desktop.close_window",
        "desktop.quit_app",
    ]


def test_runtime_planner_uses_browser_screenshot_tool_from_catalog() -> None:
    decision = RuntimePlanner().decision(
        "请调研 https://example.com 并截图",
        allowed_tools=["browser.open_url_and_screenshot", "artifact.write"],
    )

    assert decision.selected_intent.kind == "web_research"
    assert decision.plan.tool_plan.missing_capabilities == []
    assert _step_by_id(decision, "capture-web-url").tool_name == "browser.open_url_and_screenshot"
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


def test_runtime_planner_routes_relative_reminder_to_schedule_capability() -> None:
    tomorrow_0900 = f"{(date.today() + timedelta(days=1)).isoformat()}T09:00"
    decision = RuntimePlanner().decision(
        "提醒我明天买牛奶",
        allowed_tools=["reminders.create"],
    )

    assert decision.selected_intent.kind == "schedule"
    step = _step_by_id(decision, "create-schedule-item")
    assert step.tool_name == "reminders.create"
    assert step.input_preview == {"title": "买牛奶", "due_at": tomorrow_0900}


def test_runtime_planner_routes_relative_calendar_event_to_schedule_capability() -> None:
    tomorrow_1500 = f"{(date.today() + timedelta(days=1)).isoformat()}T15:00"
    tomorrow_1600 = f"{(date.today() + timedelta(days=1)).isoformat()}T16:00"
    decision = RuntimePlanner().decision(
        "明天下午三点日历上加一个开会",
        allowed_tools=["calendar.create_event"],
    )

    assert decision.selected_intent.kind == "schedule"
    step = _step_by_id(decision, "create-schedule-item")
    assert step.tool_name == "calendar.create_event"
    assert step.input_preview == {
        "title": "开会",
        "start_at": tomorrow_1500,
        "end_at": tomorrow_1600,
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


def test_planner_direct_tool_requests_maps_app_scoped_search_sequence() -> None:
    requests = planner_direct_tool_requests(
        "在 Spotify 搜索 lo-fi",
        allowed_tools=[
            "desktop.list_apps",
            "app.open",
            "desktop.safe_shortcut",
            "desktop.click_ui_element",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.ui_elements",
            "browser.open_url",
        ],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Spotify"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "lo-fi"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]

    assert planner_direct_tool_requests(
        "search WeChat for file transfer",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.ui_elements",
            "browser.open_url",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "WeChat"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "file transfer"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]

    first_result_requests = planner_direct_tool_requests(
        "Slack search Alice then choose first result",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.click_ui_element",
            "desktop.ui_elements",
        ],
    )
    assert first_result_requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Slack"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.click_ui_element",
            "input": {"target": "first result", "role_filter": "", "limit": 80, "click_count": 1},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]

    chinese_alias_requests = planner_direct_tool_requests(
        "切到微信，搜索张三",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "browser.open_url",
        ],
    )
    assert chinese_alias_requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "WeChat"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "张三"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]

    command_palette_requests = planner_direct_tool_requests(
        "切到 Obsidian 打开命令面板输入 Toggle reading view 并回车",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
    )
    assert command_palette_requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Obsidian", "action": "obsidian_command_palette"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Toggle reading view"},
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

    assert planner_direct_tool_requests(
        "打开 Obsidian 命令面板",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.ui_elements",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Obsidian", "action": "obsidian_command_palette"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]

    command_palette_key_requests = planner_direct_tool_requests(
        "在 VS Code 里打开命令面板输入 Format Document 后按下箭头再确认",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.safe_key",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
    )
    assert command_palette_key_requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_key",
            "input": {"action": "arrow_down", "repeat_count": 1},
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


def test_planner_selection_owns_app_search_send_sequence_with_send_approval() -> None:
    selection = planner_first_direct_tool_selection(
        "Slack search yachiyo and send hello",
        [
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
            "desktop.active_window",
            "app.open_and_safe_type_text",
        ],
        legacy_tool_requests=lambda _prompt, _allowed_tools: [
            {
                "protocol": "json_fallback",
                "tool": "app.focus_and_safe_shortcut",
                "input": {"app_name": "Slack", "action": "find"},
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_type_text",
                "input": {"text": "yachiyo"},
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.search_submit",
                "input": {},
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.submit_foreground",
                "input": {"action": "send"},
            },
        ],
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.event_payload["intent_kind"] == "communication"
    assert selection.event_payload["legacy_request_count"] == 0
    assert selection.event_payload["selected_tools"] == [
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_type_text",
        "desktop.submit_foreground",
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


def test_planner_desktop_tool_requests_maps_explicit_discovery_actions() -> None:
    allowed_tools = [
        "desktop.permissions",
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.list_apps",
    ]

    assert planner_tool_requests("需要什么权限", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.permissions",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]
    assert planner_tool_requests("当前窗口是什么", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]
    assert planner_tool_requests("当前有哪些 App 在运行", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.running_apps",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]
    assert planner_tool_requests("show installed apps", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]
    assert planner_tool_requests("我现在是不是在家", allowed_tools) == []


def test_planner_direct_tool_requests_omits_discover_and_verify_steps() -> None:
    requests = planner_direct_tool_requests(
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
                "click_count": 1,
                "limit": 80,
            },
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]


def test_planner_direct_tool_requests_maps_foreground_browser_safe_shortcuts() -> None:
    cases = [
        ("刷新当前网页", "refresh"),
        ("open a new tab", "new_tab"),
        ("关闭当前标签页", "close_tab"),
        ("把当前网页加入书签", "bookmark_page"),
    ]

    for prompt, action in cases:
        requests = planner_direct_tool_requests(
            prompt,
            allowed_tools=[
                "desktop.active_window",
                "desktop.safe_shortcut",
                "desktop.ui_elements",
            ],
        )

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_shortcut",
                "input": {"action": action},
                "source": "runtime_planner",
                "planning_reason": "planner_fallback_desktop_operation",
            }
        ]


def test_entrypoint_selection_keeps_runtime_planner_for_system_settings_open() -> None:
    legacy_calls: list[dict[str, Any]] = []

    decision, requests = planner_first_direct_decision_and_tool_requests(
        "打开蓝牙",
        allowed_tools=[
            "desktop.list_apps",
            "app.open",
            "desktop.active_window",
            "system.settings_open",
        ],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert decision is not None
    assert decision.selected_intent.kind == "system_control"
    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "system.settings_open",
            "input": {"target": "蓝牙"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_system_control",
        }
    ]
    assert legacy_calls == []


def test_entrypoint_selection_keeps_runtime_planner_for_strong_multi_step_plan() -> None:
    legacy_calls: list[dict[str, Any]] = []

    decision, requests = planner_first_direct_decision_and_tool_requests(
        "打开 PixelForge 并点击导出按钮",
        allowed_tools=[
            "desktop.list_apps",
            "app.open",
            "desktop.click_ui_element",
            "desktop.ui_elements",
        ],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert decision is not None
    assert [request["tool"] for request in requests] == [
        "app.open",
        "desktop.click_ui_element",
    ]
    assert legacy_calls == []


def test_entrypoint_selection_keeps_runtime_planner_for_current_page_find() -> None:
    legacy_calls: list[dict[str, Any]] = []

    selection = planner_first_direct_tool_selection(
        "用剪贴板内容查找当前网页",
        ["desktop.safe_shortcut", "desktop.safe_type_text", "clipboard.read"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.event_payload["selection_source"] == "runtime_planner"
    assert selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_current_page_find",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_current_page_find",
        },
    ]
    assert legacy_calls == []


def test_entrypoint_selection_keeps_runtime_planner_for_matching_safe_shortcuts() -> None:
    actions_by_prompt = {
        "刷新当前网页": "refresh",
        "open a new tab": "new_tab",
        "关闭当前标签页": "close_tab",
        "把当前网页加入书签": "bookmark_page",
    }

    def legacy_requests(prompt: str, _allowed_tools: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_shortcut",
                "input": {"action": actions_by_prompt[prompt]},
            }
        ]

    for prompt, action in actions_by_prompt.items():
        selection = planner_first_direct_tool_selection(
            prompt,
            ["desktop.active_window", "desktop.safe_shortcut", "desktop.ui_elements"],
            legacy_tool_requests=legacy_requests,
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["selection_source"] == "runtime_planner"
        assert selection.requests == [
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_shortcut",
                "input": {"action": action},
                "source": "runtime_planner",
                "planning_reason": "planner_fallback_desktop_operation",
            }
        ]


def test_entrypoint_selection_keeps_runtime_planner_for_matching_url_open() -> None:
    legacy_calls: list[dict[str, Any]] = []

    def legacy_requests(prompt: str, _allowed_tools: list[str]) -> list[dict[str, Any]]:
        legacy_calls.append({"prompt": prompt, "allowed_tools": list(_allowed_tools)})
        if "127.0.0.1" in prompt:
            return [
                {
                    "protocol": "json_fallback",
                    "tool": "browser.open_url",
                    "input": {"url": "http://127.0.0.1:5173"},
                }
            ]
        return [
            {
                "protocol": "json_fallback",
                "tool": "browser.open_url",
                "input": {"url": "https://example.com"},
            }
        ]

    selection = planner_first_direct_tool_selection(
        "打开 https://example.com",
        ["browser.open_url", "browser.open_url_and_extract_text"],
        legacy_tool_requests=legacy_requests,
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.event_payload["legacy_request_count"] == 0
    assert selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://example.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert legacy_calls == []

    local_selection = planner_first_direct_tool_selection(
        "打开 127.0.0.1:5173",
        ["browser.open_url", "desktop.open_path"],
        legacy_tool_requests=legacy_requests,
    )

    assert local_selection.selected_source == "runtime_planner"
    assert local_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "http://127.0.0.1:5173"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert legacy_calls == []


def test_entrypoint_selection_keeps_runtime_planner_for_matching_url_extract() -> None:
    legacy_calls: list[dict[str, Any]] = []

    def legacy_requests(prompt: str, _allowed_tools: list[str]) -> list[dict[str, Any]]:
        legacy_calls.append({"prompt": prompt, "allowed_tools": list(_allowed_tools)})
        request = {
            "protocol": "json_fallback",
            "tool": "browser.open_url_and_extract_text",
            "input": {"url": "https://github.com"},
        }
        if "summarize" in prompt:
            request["presentation"] = "summary"
        return [request]

    selection = planner_first_direct_tool_selection(
        "open github.com and summarize",
        ["browser.open_url_and_extract_text", "browser.open_url"],
        legacy_tool_requests=legacy_requests,
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.event_payload["legacy_request_count"] == 0
    assert selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url_and_extract_text",
            "input": {"url": "https://github.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
            "presentation": "summary",
        }
    ]
    assert legacy_calls == []


def test_entrypoint_selection_resolves_known_web_destinations_without_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    selection = planner_first_direct_tool_selection(
        "打开 GitHub",
        ["browser.open_url", "app.open", "desktop.list_apps"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    bilibili_selection = planner_first_direct_tool_selection(
        "打开 B 站首页",
        ["browser.open_url", "app.open", "desktop.list_apps"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    reddit_selection = planner_first_direct_tool_selection(
        "open Reddit",
        ["browser.open_url", "app.open", "desktop.list_apps"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    drive_selection = planner_first_direct_tool_selection(
        "打开 Google Drive",
        ["browser.open_url", "app.open", "desktop.list_apps"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    youtube_music_selection = planner_first_direct_tool_selection(
        "打开 YouTube Music",
        ["browser.open_url", "app.open", "desktop.list_apps"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    app_selection = planner_first_direct_tool_selection(
        "打开 Notion",
        ["browser.open_url", "app.open", "desktop.list_apps"],
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.event_payload["intent_kind"] == "web_research"
    assert selection.event_payload["legacy_request_count"] == 0
    assert selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://github.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert bilibili_selection.selected_source == "runtime_planner"
    assert bilibili_selection.event_payload["intent_kind"] == "web_research"
    assert bilibili_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.bilibili.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert reddit_selection.selected_source == "runtime_planner"
    assert reddit_selection.event_payload["intent_kind"] == "web_research"
    assert reddit_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.reddit.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert drive_selection.selected_source == "runtime_planner"
    assert drive_selection.event_payload["intent_kind"] == "web_research"
    assert drive_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://drive.google.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert youtube_music_selection.selected_source == "runtime_planner"
    assert youtube_music_selection.event_payload["intent_kind"] == "web_research"
    assert youtube_music_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://music.youtube.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert app_selection.selected_source == "runtime_planner"
    assert app_selection.event_payload["intent_kind"] == "desktop_operation"
    assert app_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Notion"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]
    assert legacy_calls == []


def test_entrypoint_selection_preserves_browser_field_input_approval() -> None:
    search_selector = (
        'input[type="search"], input[name="q"], textarea[name="q"], '
        'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
        'input[aria-label*="search" i], input[placeholder*="search" i]'
    )

    def legacy_requests(_prompt: str, _allowed_tools: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "protocol": "json_fallback",
                "tool": "browser.type_text",
                "input": {"selector": search_selector, "text": "hello"},
            }
        ]

    selection = planner_first_direct_tool_selection(
        "type hello in current webpage search field into input on current page",
        [
            "browser.type_text",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "app.open_and_safe_type_text",
            "desktop.submit_foreground",
        ],
        legacy_tool_requests=legacy_requests,
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.event_payload["selection_reason"] == "runtime_planner_direct"
    assert selection.decision is not None
    assert selection.decision.selected_intent.kind == "web_research"
    assert selection.decision.selected_intent.inputs["browser_action"] == "type_text"
    step = selection.decision.plan.tool_plan.steps[0]
    assert step.step_id == "type-current-page-input"
    assert step.tool_name == "browser.type_text"
    assert step.approval_required is True
    assert selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.type_text",
            "input": {"selector": search_selector, "text": "hello"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]


def test_entrypoint_selection_routes_browser_click_to_planner() -> None:
    def legacy_requests(_prompt: str, _allowed_tools: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "protocol": "json_fallback",
                "tool": "browser.click",
                "input": {"selector": "search-result=1", "click_count": 1},
            }
        ]

    for prompt in (
        "click the first search result",
        "点击当前页面第一个搜索结果",
    ):
        selection = planner_first_direct_tool_selection(
            prompt,
            [
                "browser.click",
                "desktop.click_ui_element",
                "app.open_and_click_ui_element",
            ],
            legacy_tool_requests=legacy_requests,
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["selection_reason"] == "runtime_planner_direct"
        assert selection.decision is not None
        assert selection.decision.selected_intent.kind == "web_research"
        assert selection.decision.selected_intent.inputs["browser_action"] == "click"
        step = selection.decision.plan.tool_plan.steps[0]
        assert step.step_id == "click-current-page-element"
        assert step.tool_name == "browser.click"
        assert step.approval_required is True
        assert selection.requests == [
            {
                "protocol": "json_fallback",
                "tool": "browser.click",
                "input": {"selector": "search-result=1", "click_count": 1},
                "source": "runtime_planner",
                "planning_reason": "planner_fallback_web_research",
            }
        ]

    desktop = RuntimePlanner().decision(
        "点击可见的登录按钮",
        allowed_tools=["browser.click", "desktop.click_ui_element"],
    )
    assert desktop.selected_intent.kind == "desktop_operation"
    assert _step_by_id(desktop, "operate-foreground-ui").tool_name == "desktop.click_ui_element"


def test_entrypoint_selection_routes_web_search_first_result_sequence_to_planner() -> None:
    legacy_calls: list[dict[str, Any]] = []

    def legacy_requests(prompt: str, allowed_tools: list[str]) -> list[dict[str, Any]]:
        legacy_calls.append({"prompt": prompt, "allowed_tools": list(allowed_tools)})
        return [
            {
                "protocol": "json_fallback",
                "tool": "app.focus",
                "input": {"app_name": "Google Chrome"},
            },
            {
                "protocol": "json_fallback",
                "tool": "browser.open_url",
                "input": {"url": "https://www.google.com/search?q=OpenAI"},
            },
            {
                "protocol": "json_fallback",
                "tool": "browser.click",
                "input": {"selector": "search-result=1", "click_count": 1},
            },
        ]

    selection = planner_first_direct_tool_selection(
        "Chrome 搜索 OpenAI 并打开第一个结果",
        ["browser.open_url", "browser.click", "app.focus"],
        metadata={"daily_desktop_intent": True},
        legacy_tool_requests=legacy_requests,
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.decision is not None
    assert selection.decision.selected_intent.kind == "web_research"
    assert selection.decision.selected_intent.inputs["followup_action"] == (
        "click_search_result"
    )
    assert selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=OpenAI"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        },
    ]
    assert legacy_calls == []


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


def test_planner_desktop_tool_requests_maps_named_app_management() -> None:
    requests = planner_desktop_tool_requests(
        "最小化 Slack",
        allowed_tools=["desktop.list_apps", "app.minimize", "desktop.running_apps"],
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
            "tool": "app.minimize",
            "input": {"app_name": "Slack"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.running_apps",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]


def test_planner_direct_tool_requests_maps_app_management_sequence() -> None:
    requests = planner_direct_tool_requests(
        "打开 Slack 然后隐藏",
        allowed_tools=["desktop.list_apps", "app.open", "app.hide", "desktop.running_apps"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Slack"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "app.hide",
            "input": {"app_name": "Slack"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
    ]


def test_planner_desktop_tool_requests_maps_foreground_window_management() -> None:
    requests = planner_desktop_tool_requests(
        "关闭当前窗口",
        allowed_tools=["desktop.active_window", "desktop.close_window"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.close_window",
            "input": {},
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


def test_planner_desktop_tool_requests_maps_named_music_query_to_app_search_plan() -> None:
    requests = planner_desktop_tool_requests(
        "在 Spotify 播放 lo-fi",
        allowed_tools=[
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "media.music_app_open_and_play",
        ],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Spotify", "action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_media_playback",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "lo-fi"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_media_playback",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_media_playback",
        },
    ]


def test_planner_desktop_tool_requests_normalizes_named_music_app_control() -> None:
    requests = planner_desktop_tool_requests(
        "QQ Music next track",
        allowed_tools=["media.music_app_control", "media.system_control"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "media.music_app_control",
            "input": {"app_name": "QQ音乐", "action": "next"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_media_playback",
        },
    ]


def test_planner_desktop_tool_requests_keeps_generic_music_control_system_scoped() -> None:
    requests = planner_desktop_tool_requests(
        "关掉音乐",
        allowed_tools=["media.apple_music_control", "media.system_control"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "media.system_control",
            "input": {"action": "pause"},
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

    assert planner_tool_requests(
        "open sound settings",
        allowed_tools=["system.settings_open"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "system.settings_open",
            "input": {"target": "声音"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_system_control",
        }
    ]
    assert planner_tool_requests(
        "打开系统设置看看有哪些选项",
        allowed_tools=["system.settings_open", "desktop.ui_elements"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "system.settings_open",
            "input": {"target": "系统设置"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_system_control",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "", "limit": 80},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_system_control",
        },
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


def test_planner_tool_requests_prefetches_context_data_source_for_analysis() -> None:
    selection_requests = planner_tool_requests(
        "分析当前选中的数据并生成报告",
        allowed_tools=["desktop.safe_shortcut", "clipboard.read", "terminal.run", "artifact.write"],
    )
    clipboard_requests = planner_tool_requests(
        "分析剪贴板里的表格并输出 csv",
        allowed_tools=["clipboard.read", "terminal.run", "artifact.write"],
    )
    report_requests = planner_tool_requests(
        "把选中的内容做成报告",
        allowed_tools=["desktop.safe_shortcut", "clipboard.read", "artifact.write"],
    )

    assert selection_requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_data_source",
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_data_source",
            "continue_to_model": True,
        },
    ]
    assert clipboard_requests == [
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_data_source",
            "continue_to_model": True,
        }
    ]
    assert [request["planning_reason"] for request in report_requests] == [
        "planner_prefetch_report_context",
        "planner_prefetch_report_context",
    ]


def test_planner_tool_requests_discovers_data_source_for_analysis() -> None:
    scoped_requests = planner_tool_requests(
        "分析 Downloads 里的销售数据并输出报告",
        allowed_tools=["workspace.list", "workspace.read", "terminal.run", "artifact.write"],
    )
    generic_requests = planner_tool_requests(
        "分析数据并输出报告",
        allowed_tools=["workspace.list", "workspace.read", "terminal.run", "artifact.write"],
    )

    assert scoped_requests == [
        {
            "protocol": "json_fallback",
            "tool": "workspace.list",
            "input": {"path": "Downloads"},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_data_source",
            "continue_to_model": True,
        }
    ]
    assert generic_requests == [
        {
            "protocol": "json_fallback",
            "tool": "workspace.list",
            "input": {},
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


def test_planner_tool_requests_passes_builtin_data_analysis_artifact_paths() -> None:
    requests = planner_tool_requests(
        "分析 data/metrics.xlsx 并输出 html 报告、csv 汇总和图表",
        allowed_tools=["data.analyze", "workspace.read", "terminal.run", "artifact.write"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "data.analyze",
            "input": {
                "path": "data/metrics.xlsx",
                "artifact_path": "analysis-report.md",
                "artifact_paths": [
                    "analysis-report.md",
                    "analysis-chart.png",
                    "analysis-summary.csv",
                    "analysis-report.html",
                ],
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
    assert (
        planner_tool_requests(
            "请分析 /tmp 里的数据",
            allowed_tools=["workspace.list", "workspace.read", "terminal.run", "artifact.write"],
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


def test_planner_tool_requests_prefers_safe_shortcut_for_whitelisted_hotkey() -> None:
    requests = planner_tool_requests(
        "Can you press Command C?",
        allowed_tools=["desktop.safe_shortcut", "desktop.hotkey"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]


def test_planner_tool_requests_maps_safe_key_scroll_and_click() -> None:
    assert planner_tool_requests(
        "按下一页键",
        allowed_tools=["desktop.active_window", "desktop.safe_key"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_key",
            "input": {"action": "page_down", "repeat_count": 1},
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

    assert planner_tool_requests(
        "向上滚动三页",
        allowed_tools=["desktop.active_window", "desktop.safe_scroll"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_scroll",
            "input": {"direction": "up", "pages": 3},
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

    assert planner_tool_requests(
        "点击坐标 120, 240",
        allowed_tools=["desktop.active_window", "desktop.safe_click"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_click",
            "input": {"x": 120, "y": 240},
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


def test_planner_tool_requests_maps_app_hotkey_plan() -> None:
    requests = planner_tool_requests(
        "open Chrome and press command l",
        allowed_tools=["app.open_and_hotkey", "app.open_and_click_ui_element"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_hotkey",
            "input": {"app_name": "Google Chrome", "key": "l", "modifiers": ["command"]},
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


def test_planner_tool_requests_maps_current_page_browser_actions() -> None:
    allowed = [
        "browser.current_page",
        "browser.extract_text",
        "browser.screenshot",
        "screen.capture",
    ]

    assert planner_tool_requests("screenshot this page", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.screenshot",
            "input": {"reason": "user asked to capture the browser page"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert planner_tool_requests("总结当前网页", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.extract_text",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
            "presentation": "summary",
        }
    ]
    assert planner_tool_requests("what is this page about", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.extract_text",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
            "presentation": "summary",
        }
    ]
    assert planner_tool_requests("读取当前网页内容", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.extract_text",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert planner_tool_requests("读取当前网页链接", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.current_page",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]


def test_planner_tool_requests_maps_current_page_find_actions() -> None:
    allowed = [
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "clipboard.read",
        "browser.open_url",
    ]

    assert planner_tool_requests("search current page for hello", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_current_page_find",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_current_page_find",
        },
    ]
    assert planner_tool_requests("在当前网页查找当前选中文字", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_current_page_find",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_current_page_find",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_current_page_find",
        },
    ]
    assert planner_tool_requests("用剪贴板内容查找当前网页", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_current_page_find",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_current_page_find",
        },
    ]


def test_planner_tool_requests_maps_static_web_search() -> None:
    allowed = ["browser.open_url", "browser.open_url_and_extract_text", "browser.click"]

    assert planner_tool_requests("Can you search Chrome for weather?", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=weather"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert planner_tool_requests(
        "Chrome 搜索 OpenAI 并打开第一个结果",
        allowed_tools=allowed,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=OpenAI"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        },
    ]
    assert planner_tool_requests("百度 open hanako", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.baidu.com/s?wd=open+hanako"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert planner_tool_requests("search Google for open hanako", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=open+hanako"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert planner_tool_requests("搜索天气", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=%E5%A4%A9%E6%B0%94"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert planner_tool_requests(
        "search selected text",
        allowed_tools=["desktop.safe_shortcut", "desktop.search_submit", "browser.open_url"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "focus_address_bar"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
    ]


def test_planner_tool_requests_maps_explicit_browser_url_open_actions() -> None:
    allowed = [
        "browser.open_url",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
    ]

    assert planner_tool_requests("打开 https://example.com", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://example.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert planner_tool_requests("打开 127.0.0.1:5173", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "http://127.0.0.1:5173"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert planner_tool_requests("open 192.168.1.10:8000/status", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "http://192.168.1.10:8000/status"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert planner_tool_requests("打开网页 github.com", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://github.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert planner_tool_requests("打开 github.com 读一下内容", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url_and_extract_text",
            "input": {"url": "https://github.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert planner_tool_requests("open github.com and summarize", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url_and_extract_text",
            "input": {"url": "https://github.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
            "presentation": "summary",
        }
    ]
    assert planner_tool_requests("请调研 https://example.com 并截图", allowed_tools=allowed) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url_and_screenshot",
            "input": {
                "url": "https://example.com",
                "reason": "user asked to capture the browser page after opening a URL",
            },
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
        }
    ]
    assert planner_tool_requests(
        "请调研 https://example.com 并总结报告",
        allowed_tools=allowed,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url_and_extract_text",
            "input": {"url": "https://example.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
            "continue_to_model": True,
        }
    ]


def test_planner_tool_requests_maps_local_file_access_plan() -> None:
    assert planner_tool_requests(
        "打开下载目录里的最新文件",
        allowed_tools=["desktop.open_path", "desktop.reveal_path"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.open_path",
            "input": {"path": "latest_download"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_file_access",
        }
    ]
    assert planner_tool_requests(
        "显示当前选中文件",
        allowed_tools=["desktop.open_path", "desktop.reveal_path"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.reveal_path",
            "input": {"path": "finder_selection"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_file_access",
        }
    ]
    assert planner_tool_requests(
        "打开 Public 文件夹",
        allowed_tools=["desktop.open_path", "app.open"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.open_path",
            "input": {"path": "~/Public"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_file_access",
        }
    ]
    assert planner_tool_requests(
        "打开 Music 文件夹",
        allowed_tools=["desktop.open_path", "app.open"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.open_path",
            "input": {"path": "~/Music"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_file_access",
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


def test_planner_tool_requests_maps_dynamic_web_context_actions() -> None:
    assert planner_tool_requests(
        "search selected text",
        allowed_tools=["desktop.safe_shortcut", "desktop.search_submit", "browser.open_url"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "focus_address_bar"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
    ]
    assert planner_tool_requests(
        "open clipboard link",
        allowed_tools=["desktop.safe_shortcut", "desktop.search_submit", "browser.open_url"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "focus_address_bar"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        }
    ]


def test_planner_tool_requests_prefetches_report_context_for_model_loop() -> None:
    requests = planner_tool_requests(
        "写一份项目总结报告",
        allowed_tools=["workspace.read", "workspace.list", "artifact.write"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "workspace.list",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_report_context",
            "continue_to_model": True,
        }
    ]

    clipboard_requests = planner_tool_requests(
        "把剪贴板内容做成报告",
        allowed_tools=["clipboard.read", "artifact.write"],
    )

    assert clipboard_requests == [
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_report_context",
            "continue_to_model": True,
        }
    ]

    selection_requests = planner_tool_requests(
        "把选中的内容做成报告",
        allowed_tools=["desktop.safe_shortcut", "clipboard.read", "artifact.write"],
    )

    assert selection_requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_report_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_report_context",
            "continue_to_model": True,
        },
    ]


def test_planner_tool_requests_prefetches_code_context_for_model_loop() -> None:
    requests = planner_tool_requests(
        "检查这个仓库的代码并总结风险",
        allowed_tools=["workspace.list", "workspace.read", "terminal.run", "artifact.write"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "workspace.list",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_code_context",
            "continue_to_model": True,
        }
    ]


def test_planner_tool_requests_prefetches_file_scope_for_model_loop() -> None:
    requests = planner_tool_requests(
        "整理 Downloads 里的文件并按类型归档",
        allowed_tools=["workspace.list", "artifact.write", "terminal.run"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "workspace.list",
            "input": {"path": "Downloads"},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_file_scope",
            "continue_to_model": True,
        }
    ]


def test_planner_tool_requests_prefetches_communication_surface_for_model_loop() -> None:
    requests = planner_tool_requests(
        "发送消息给 Alice：今晚八点见",
        allowed_tools=["desktop.active_window", "desktop.type_into_ui_element", "artifact.write"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_communication_surface",
            "continue_to_model": True,
        }
    ]


def test_planner_tool_requests_prefetches_dynamic_communication_context() -> None:
    assert planner_tool_requests(
        "微信给文件传输助手发送选中的内容",
        allowed_tools=["desktop.safe_shortcut", "clipboard.read", "artifact.write"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_communication_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_communication_context",
            "continue_to_model": True,
        },
    ]
    assert planner_tool_requests(
        "把当前网页链接发给微信文件传输助手",
        allowed_tools=["browser.current_page", "artifact.write"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.current_page",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_communication_context",
            "continue_to_model": True,
        }
    ]
    assert planner_tool_requests(
        "把当前网页内容发给微信文件传输助手",
        allowed_tools=["browser.extract_text", "artifact.write"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.extract_text",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_communication_context",
            "continue_to_model": True,
        }
    ]


def test_planner_tool_requests_maps_direct_context_communication_send_plan() -> None:
    assert planner_tool_requests(
        "send clipboard contents in Slack to yachiyo",
        allowed_tools=[
            "app.focus_and_safe_shortcut",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_communication_send",
        },
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


def test_planner_tool_requests_maps_relative_schedule_plans() -> None:
    tomorrow_0900 = f"{(date.today() + timedelta(days=1)).isoformat()}T09:00"
    tomorrow_1500 = f"{(date.today() + timedelta(days=1)).isoformat()}T15:00"
    tomorrow_1600 = f"{(date.today() + timedelta(days=1)).isoformat()}T16:00"

    assert planner_tool_requests(
        "提醒我明天买牛奶",
        allowed_tools=["reminders.create"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "买牛奶", "due_at": tomorrow_0900},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_schedule",
        }
    ]
    assert planner_tool_requests(
        "明天下午三点日历上加一个开会",
        allowed_tools=["calendar.create_event"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "calendar.create_event",
            "input": {
                "title": "开会",
                "start_at": tomorrow_1500,
                "end_at": tomorrow_1600,
            },
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_schedule",
        }
    ]
    assert (
        planner_tool_requests(
            "add meeting tomorrow to calendar",
            allowed_tools=["calendar.create_event"],
        )
        == []
    )


def test_planner_tool_requests_prefetches_dynamic_schedule_sources_for_model_loop() -> None:
    assert planner_tool_requests(
        "create a reminder from selected text",
        allowed_tools=["reminders.create", "desktop.safe_shortcut", "clipboard.read"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_schedule_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_schedule_context",
            "continue_to_model": True,
        },
    ]
    assert planner_tool_requests(
        "把剪贴板内容创建成日历事件",
        allowed_tools=["calendar.create_event", "clipboard.read"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_schedule_context",
            "continue_to_model": True,
        }
    ]
    assert planner_tool_requests(
        "把当前页面内容创建成日历事件",
        allowed_tools=["calendar.create_event", "browser.extract_text"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.extract_text",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_schedule_context",
            "continue_to_model": True,
        }
    ]


def test_planner_tool_requests_maps_explicit_note_plan() -> None:
    requests = planner_tool_requests(
        "在 Notes 新建笔记 hello",
        allowed_tools=["notes.create"],
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "hello"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_information_capture",
        }
    ]


def test_planner_tool_requests_prefetches_context_note_for_model_loop() -> None:
    assert planner_tool_requests(
        "create a note from selected text",
        allowed_tools=["notes.create", "desktop.safe_shortcut", "clipboard.read"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_information_capture_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_information_capture_context",
            "continue_to_model": True,
        },
    ]
    assert planner_tool_requests(
        "create a note from clipboard",
        allowed_tools=["notes.create", "clipboard.read"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_information_capture_context",
            "continue_to_model": True,
        }
    ]
    assert planner_tool_requests(
        "create a note from current page link",
        allowed_tools=["notes.create", "browser.current_page"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.current_page",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_information_capture_context",
            "continue_to_model": True,
        }
    ]


def test_planner_first_keeps_migrated_context_prefetch_over_legacy_sequence() -> None:
    def legacy_requests(_prompt: str, _allowed_tools: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "protocol": "json_fallback",
                "tool": "app.open_and_safe_shortcut",
                "input": {"app_name": "Notes", "action": "new_note"},
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_shortcut",
                "input": {"action": "paste"},
            },
        ]

    selection = planner_first_direct_tool_selection(
        "create a note from clipboard",
        ["notes.create", "clipboard.read", "app.open_and_safe_shortcut", "desktop.safe_shortcut"],
        legacy_tool_requests=legacy_requests,
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.event_payload["selection_source"] == "runtime_planner"
    assert selection.event_payload["legacy_request_count"] == 0
    assert selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_information_capture_context",
            "continue_to_model": True,
        }
    ]

    communication_selection = planner_first_direct_tool_selection(
        "把当前网页链接发给微信文件传输助手",
        ["browser.current_page", "artifact.write", "app.open_and_safe_shortcut", "desktop.safe_shortcut"],
        legacy_tool_requests=legacy_requests,
    )

    assert communication_selection.selected_source == "runtime_planner"
    assert communication_selection.event_payload["selection_source"] == "runtime_planner"
    assert communication_selection.event_payload["legacy_request_count"] == 0
    assert communication_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "browser.current_page",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_communication_context",
            "continue_to_model": True,
        }
    ]

    web_selection = planner_first_direct_tool_selection(
        "open clipboard link",
        [
            "clipboard.read",
            "browser.open_url",
            "app.open_and_safe_shortcut",
            "desktop.safe_shortcut",
            "desktop.search_submit",
        ],
        legacy_tool_requests=legacy_requests,
    )

    assert web_selection.selected_source == "runtime_planner"
    assert web_selection.event_payload["selection_source"] == "runtime_planner"
    assert web_selection.event_payload["legacy_request_count"] == 0
    assert web_selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "focus_address_bar"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_dynamic_browser_context",
        },
    ]


def test_planner_first_routes_terminal_command_on_planner_approval_path() -> None:
    legacy_calls: list[dict[str, Any]] = []

    def legacy_requests(prompt: str, allowed_tools: list[str]) -> list[dict[str, Any]]:
        legacy_calls.append({"prompt": prompt, "allowed_tools": list(allowed_tools)})
        return [
            {
                "protocol": "json_fallback",
                "tool": "terminal.run",
                "input": {"command": "ls"},
            }
        ]

    selection = planner_first_direct_tool_selection(
        "打开终端运行 ls",
        ["app.open", "desktop.list_apps", "terminal.run"],
        legacy_tool_requests=legacy_requests,
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.event_payload["selection_source"] == "runtime_planner"
    assert selection.event_payload["legacy_request_count"] == 0
    assert selection.event_payload["intent_kind"] == "code_task"
    assert selection.requests == [
        {
            "protocol": "json_fallback",
            "tool": "terminal.run",
            "input": {"command": "ls"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_terminal_command",
        }
    ]
    assert legacy_calls == []


def test_planner_first_owns_direct_context_communication_send_sequence() -> None:
    def legacy_requests(_prompt: str, _allowed_tools: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_shortcut",
                "input": {"action": "copy"},
            }
        ]

    selection = planner_first_direct_tool_selection(
        "send selected text in Slack to yachiyo",
        [
            "app.focus_and_safe_shortcut",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
        ],
        legacy_tool_requests=legacy_requests,
    )

    assert selection.selected_source == "runtime_planner"
    assert selection.event_payload["selection_source"] == "runtime_planner"
    assert selection.event_payload["legacy_request_count"] == 0
    assert [request["tool"] for request in selection.requests] == [
        "desktop.safe_shortcut",
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_shortcut",
        "desktop.submit_foreground",
    ]
    assert all(
        request["planning_reason"] == "planner_fallback_communication_send"
        for request in selection.requests
    )


def test_planner_first_owns_desktop_discovery_requests_over_legacy() -> None:
    def legacy_requests(_prompt: str, _allowed_tools: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "protocol": "json_fallback",
                "tool": "screen.capture",
                "input": {"reason": "legacy fallback"},
            }
        ]

    current_ui = planner_first_direct_tool_selection(
        "当前界面有哪些按钮",
        ["desktop.active_window", "desktop.ui_elements", "screen.capture"],
        legacy_tool_requests=legacy_requests,
    )
    list_apps = planner_first_direct_tool_selection(
        "列出所有应用",
        ["desktop.list_apps", "desktop.running_apps"],
        legacy_tool_requests=legacy_requests,
    )

    assert current_ui.selected_source == "runtime_planner"
    assert current_ui.event_payload["legacy_request_count"] == 0
    assert current_ui.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "button", "limit": 80},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]
    assert list_apps.selected_source == "runtime_planner"
    assert list_apps.event_payload["legacy_request_count"] == 0
    assert list_apps.requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_desktop_operation",
        }
    ]


def test_planner_first_owns_app_scoped_ui_observation_requests_over_legacy() -> None:
    legacy_calls: list[dict[str, Any]] = []

    app_ui = planner_first_direct_tool_selection(
        "Slack 有哪些按钮",
        ["desktop.list_apps", "app.focus", "desktop.ui_elements"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )
    app_capture = planner_first_direct_tool_selection(
        "Slack 截屏",
        ["desktop.list_apps", "app.focus", "screen.capture"],
        legacy_tool_requests=_recording_legacy_requests(legacy_calls),
    )

    assert app_ui.selected_source == "runtime_planner"
    assert app_ui.event_payload["legacy_request_count"] == 0
    assert app_ui.requests == [
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
    assert app_capture.selected_source == "runtime_planner"
    assert app_capture.event_payload["legacy_request_count"] == 0
    assert app_capture.requests == [
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
    assert legacy_calls == []


def test_planner_first_owns_app_scoped_ui_operations_over_legacy() -> None:
    cases = (
        (
            "切到 Slack 点击搜索框",
            [
                "desktop.list_apps",
                "app.focus_and_click_ui_element",
                "desktop.click_ui_element",
                "desktop.ui_elements",
            ],
            ["app.focus_and_click_ui_element"],
        ),
        (
            "打开 Slack 点击坐标 120, 240",
            ["desktop.list_apps", "app.open_and_safe_click", "desktop.safe_click"],
            ["app.open_and_safe_click"],
        ),
        (
            "打开 Obsidian 写 hello",
            [
                "desktop.list_apps",
                "app.open_and_safe_type_text",
                "desktop.safe_type_text",
                "desktop.ui_elements",
            ],
            ["app.open_and_safe_type_text"],
        ),
        (
            "在 Notes 输入 hello",
            [
                "desktop.list_apps",
                "app.focus_and_safe_type_text",
                "app.open_and_safe_type_text",
                "desktop.safe_type_text",
            ],
            ["app.focus_and_safe_type_text"],
        ),
        (
            "Slack 回车发送",
            ["desktop.list_apps", "app.focus", "desktop.submit_foreground"],
            ["app.focus", "desktop.submit_foreground"],
        ),
    )

    for prompt, allowed_tools, expected_tools in cases:
        legacy_calls: list[dict[str, Any]] = []
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed_tools,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert [request["tool"] for request in selection.requests] == expected_tools
        assert legacy_calls == []


def test_planner_first_owns_app_window_and_management_over_legacy() -> None:
    cases = (
        (
            "切到 Slack 的主窗口",
            ["desktop.list_apps", "desktop.windows", "app.focus_window", "app.focus"],
            ["app.focus_window"],
        ),
        (
            "最小化 Safari",
            ["desktop.list_apps", "app.minimize", "desktop.running_apps"],
            ["app.minimize"],
        ),
        (
            "隐藏 Slack",
            ["desktop.list_apps", "app.hide", "desktop.running_apps"],
            ["app.hide"],
        ),
        (
            "退出 Slack",
            ["desktop.list_apps", "app.quit", "desktop.running_apps"],
            ["app.quit"],
        ),
    )

    for prompt, allowed_tools, expected_tools in cases:
        legacy_calls: list[dict[str, Any]] = []
        selection = planner_first_direct_tool_selection(
            prompt,
            allowed_tools,
            legacy_tool_requests=_recording_legacy_requests(legacy_calls),
        )

        assert selection.selected_source == "runtime_planner"
        assert selection.event_payload["legacy_request_count"] == 0
        assert [request["tool"] for request in selection.requests] == expected_tools
        assert legacy_calls == []


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
