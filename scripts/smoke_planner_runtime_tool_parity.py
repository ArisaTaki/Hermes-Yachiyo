#!/usr/bin/env python3
"""Smoke-test Runtime Planner tool choices against executable runtime tools."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.agent.tools.policy import (
    KNOWN_AGENT_TOOLS,
    RuntimePolicyCompiler,
    ToolDescriptorRegistry,
    TOOL_NAME_ALIASES,
)
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY
from apps.shell.yachiyo_agent import RuntimePlanner
from apps.shell.yachiyo_agent.planner_execution import planner_tool_requests

PLANNER_TOOL_PARITY_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "generic_app_open",
        "category": "orchestrator",
        "prompt": "打开 PixelForge",
        "expected_intent": "desktop_operation",
        "expected_plan_tools": ["desktop.list_apps", "app.open", "desktop.active_window"],
        "expected_request_tools": ["desktop.list_apps", "app.open", "desktop.active_window"],
        "approval_required": [],
    },
    {
        "id": "app_scoped_ui_click",
        "category": "orchestrator",
        "prompt": "在 Notion 点击 New Page",
        "expected_intent": "desktop_operation",
        "expected_plan_tools": [
            "desktop.inspect_app",
            "app.focus_and_click_ui_element",
            "desktop.ui_elements",
        ],
        "expected_request_tools": [
            "desktop.inspect_app",
            "app.focus_and_click_ui_element",
            "desktop.ui_elements",
        ],
        "approval_required": ["app.focus_and_click_ui_element"],
    },
    {
        "id": "app_issue_create",
        "category": "orchestrator",
        "prompt": "打开 Linear，把这个 bug 记录成 issue",
        "expected_intent": "desktop_operation",
        "expected_plan_tools": [
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.ui_elements",
        ],
        "expected_request_tools": [
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.ui_elements",
        ],
        "approval_required": [],
    },
    {
        "id": "capability_project_task_create",
        "category": "orchestrator",
        "prompt": "打开任意项目管理工具，新建任务：整理发布清单",
        "expected_intent": "desktop_operation",
        "expected_plan_tools": [
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.ui_elements",
        ],
        "expected_request_tools": [
            "desktop.list_apps",
        ],
        "approval_required": [],
    },
    {
        "id": "builtin_data_analysis",
        "category": "orchestrator",
        "prompt": "请分析 data/sales.csv 并输出报告",
        "expected_intent": "data_analysis",
        "expected_plan_tools": ["data.analyze"],
        "expected_request_tools": ["data.analyze"],
        "approval_required": [],
    },
    {
        "id": "visible_table_analysis",
        "category": "orchestrator",
        "prompt": "分析桌面上这个表格并输出报告",
        "expected_intent": "data_analysis",
        "expected_plan_tools": ["desktop.ui_elements", "data.analyze"],
        "expected_request_tools": ["desktop.ui_elements"],
        "approval_required": [],
    },
    {
        "id": "visible_table_analysis_to_document_app",
        "category": "orchestrator",
        "prompt": "分析当前窗口里的表格并把报告写进任意文档应用",
        "expected_intent": "data_analysis",
        "expected_plan_tools": [
            "desktop.ui_elements",
            "data.analyze",
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
        ],
        "expected_request_tools": ["desktop.ui_elements"],
        "approval_required": [],
    },
    {
        "id": "current_page_report",
        "category": "orchestrator",
        "prompt": "把当前网页总结成一份报告",
        "expected_intent": "web_research",
        "expected_plan_tools": ["browser.extract_text", "artifact.write"],
        "expected_request_tools": ["browser.extract_text"],
        "approval_required": [],
    },
    {
        "id": "current_page_summary_to_app",
        "category": "orchestrator",
        "prompt": "把当前网页总结到 Notion 新页面",
        "expected_intent": "report_generation",
        "expected_plan_tools": ["browser.extract_text", "app.focus"],
        "expected_request_tools": ["browser.extract_text"],
        "approval_required": [],
    },
    {
        "id": "current_page_summary_to_document_app",
        "category": "orchestrator",
        "prompt": "把当前网页总结到任意文档应用",
        "expected_intent": "report_generation",
        "expected_plan_tools": [
            "browser.extract_text",
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
        ],
        "expected_request_tools": ["browser.extract_text"],
        "approval_required": [],
    },
    {
        "id": "current_window_markdown_artifact",
        "category": "orchestrator",
        "prompt": "把当前窗口里的内容复制并保存成 markdown",
        "expected_intent": "report_generation",
        "expected_plan_tools": ["desktop.ui_elements", "artifact.write"],
        "expected_request_tools": ["desktop.ui_elements"],
        "approval_required": [],
    },
    {
        "id": "current_window_release_notes_artifact",
        "category": "orchestrator",
        "prompt": "把当前窗口里的内容整理成发布说明并保存到 Downloads",
        "expected_intent": "report_generation",
        "expected_plan_tools": ["desktop.ui_elements", "artifact.write"],
        "expected_request_tools": ["desktop.ui_elements"],
        "approval_required": [],
    },
    {
        "id": "named_media_app_playback",
        "category": "orchestrator",
        "prompt": "open VLC play test",
        "expected_intent": "media_playback",
        "expected_plan_tools": [
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "media.music_app_open_and_play",
            "desktop.ui_elements",
        ],
        "expected_request_tools": [
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "media.music_app_open_and_play",
            "desktop.ui_elements",
        ],
        "approval_required": [],
    },
    {
        "id": "capability_media_app_playback",
        "category": "orchestrator",
        "prompt": "打开任意能播放音乐的应用播放 lo-fi",
        "expected_intent": "media_playback",
        "expected_plan_tools": [
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "media.music_app_open_and_play",
            "desktop.ui_elements",
        ],
        "expected_request_tools": [
            "desktop.list_apps",
        ],
        "approval_required": [],
    },
    {
        "id": "clipboard_send_to_slack",
        "category": "orchestrator",
        "prompt": "读取剪贴板内容并发给 Slack 的 yachiyo",
        "expected_intent": "communication",
        "expected_plan_tools": [
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.safe_shortcut",
            "desktop.submit_foreground",
        ],
        "expected_request_tools": [
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.safe_shortcut",
            "desktop.submit_foreground",
        ],
        "approval_required": ["desktop.submit_foreground"],
    },
    {
        "id": "system_settings_bluetooth",
        "category": "orchestrator",
        "prompt": "打开系统设置里的蓝牙",
        "expected_intent": "system_control",
        "expected_plan_tools": ["system.settings_open"],
        "expected_request_tools": ["system.settings_open"],
        "approval_required": [],
    },
    {
        "id": "file_organize_invoices",
        "category": "orchestrator",
        "prompt": "把下载里的发票整理到一个文件夹",
        "expected_intent": "file_organization",
        "expected_plan_tools": [
            "workspace.list",
            "artifact.write",
            "file.organize",
        ],
        "expected_request_tools": ["workspace.list"],
        "approval_required": ["file.organize"],
    },
    {
        "id": "explicit_terminal_command",
        "category": "coding",
        "prompt": "run ls -la in terminal",
        "expected_intent": "code_task",
        "expected_plan_tools": ["terminal.run"],
        "expected_request_tools": ["terminal.run"],
        "approval_required": ["terminal.run"],
    },
    {
        "id": "code_diagnostic_with_workspace_context",
        "category": "coding",
        "prompt": "修复这个仓库里的 failing tests",
        "expected_intent": "code_task",
        "expected_plan_tools": ["workspace.list", "terminal.run", "artifact.write"],
        "expected_request_tools": ["workspace.list", "terminal.run"],
        "approval_required": ["terminal.run"],
    },
    {
        "id": "reminder_creation",
        "category": "orchestrator",
        "prompt": "提醒我明天九点开会",
        "expected_intent": "schedule",
        "expected_plan_tools": ["reminders.create"],
        "expected_request_tools": ["reminders.create"],
        "approval_required": [],
    },
)


def _compiled_policy(category: str) -> dict[str, Any]:
    return RuntimePolicyCompiler().compile_tool_policy(
        category,
        RuntimePolicyCompiler.default_tool_policy(category),
    )


def _descriptor_tools(tools: list[str]) -> list[str]:
    schemas = ToolDescriptorRegistry.model_tool_schemas(tools)
    return [
        TOOL_NAME_ALIASES.get(
            str(schema.get("function", {}).get("name") or "").strip(),
            str(schema.get("function", {}).get("name") or "").strip(),
        )
        for schema in schemas
        if isinstance(schema, dict)
    ]


def _case_evidence(case: dict[str, Any]) -> dict[str, Any]:
    category = str(case["category"])
    policy = _compiled_policy(category)
    allowed_tools = [str(tool) for tool in policy.get("allowed_tools") or []]
    prompt = str(case["prompt"])
    decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
    requests = planner_tool_requests(prompt, allowed_tools)
    plan_tools = [
        str(getattr(step, "tool_name", "") or "").strip()
        for step in decision.plan.tool_plan.steps
        if str(getattr(step, "tool_name", "") or "").strip()
    ]
    request_tools = [
        str(request.get("tool") or "").strip()
        for request in requests
        if str(request.get("tool") or "").strip()
    ]
    expected_plan_tools = [str(tool) for tool in case["expected_plan_tools"]]
    expected_request_tools = [str(tool) for tool in case["expected_request_tools"]]
    expected_approval_tools = [str(tool) for tool in case["approval_required"]]
    descriptor_tools = _descriptor_tools(sorted(set(plan_tools + request_tools)))
    approval_required = policy.get("approval_required")
    if not isinstance(approval_required, dict):
        approval_required = {}
    checks = {
        "intent_matches": decision.selected_intent.kind == str(case["expected_intent"]),
        "plan_tools_match": plan_tools == expected_plan_tools,
        "request_tools_match": request_tools == expected_request_tools,
        "plan_tools_registered": all(tool in KNOWN_AGENT_TOOLS for tool in plan_tools),
        "request_tools_dispatched": all(tool in TOOL_DISPATCH_REGISTRY for tool in request_tools),
        "tools_have_model_descriptors": set(plan_tools + request_tools).issubset(
            set(descriptor_tools)
        ),
        "request_tools_allowed_by_policy": all(tool in allowed_tools for tool in request_tools),
        "approval_required_matches": all(
            bool(approval_required.get(tool)) for tool in expected_approval_tools
        )
        and all(
            not bool(approval_required.get(tool))
            for tool in request_tools
            if tool not in expected_approval_tools
        ),
    }
    return {
        "id": str(case["id"]),
        "ok": all(checks.values()),
        "category": category,
        "prompt": prompt,
        "intent_kind": decision.selected_intent.kind,
        "plan_tools": plan_tools,
        "request_tools": request_tools,
        "descriptor_tools": descriptor_tools,
        "approval_required_tools": [
            tool for tool in request_tools if bool(approval_required.get(tool))
        ],
        "checks": checks,
    }


def run_smoke() -> dict[str, Any]:
    cases = [_case_evidence(case) for case in PLANNER_TOOL_PARITY_CASES]
    return {
        "ok": all(case["ok"] for case in cases),
        "mode": "planner_runtime_tool_parity_smoke",
        "case_count": len(cases),
        "cases": cases,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", type=Path, help="Optional JSON evidence report path.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = run_smoke()
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
        print(f"planner runtime tool parity smoke report: {args.report_json}", file=sys.stderr)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
