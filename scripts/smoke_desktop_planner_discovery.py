#!/usr/bin/env python3
"""Smoke-test desktop discovery/operate planner decisions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.yachiyo_agent import RuntimePlanner
from apps.shell.yachiyo_agent.planner_execution import planner_tool_requests

DESKTOP_PLANNER_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "generic_app_open",
        "prompt": "打开 PixelForge",
        "allowed_tools": ["desktop.list_apps", "app.open", "desktop.active_window"],
        "expected_app": "PixelForge",
        "expected_steps": [
            "discover-desktop-state",
            "open-or-focus-app",
            "verify-desktop-result",
        ],
        "expected_request_tools": [
            "desktop.list_apps",
            "app.open",
            "desktop.active_window",
        ],
    },
    {
        "id": "generic_app_read_buttons",
        "prompt": "打开 Linear 并读取按钮",
        "allowed_tools": [
            "desktop.inspect_app",
            "desktop.list_apps",
            "app.open",
            "desktop.ui_elements",
        ],
        "expected_app": "Linear",
        "expected_steps": [
            "inspect-app",
        ],
        "expected_request_tools": [
            "desktop.inspect_app",
        ],
    },
    {
        "id": "generic_unknown_app_sequenced_read_buttons",
        "prompt": "打开一个我没提过的新应用 PixelForge，然后读一下界面上有哪些按钮",
        "allowed_tools": [
            "desktop.list_apps",
            "app.open",
            "desktop.ui_elements",
        ],
        "expected_app": "PixelForge",
        "expected_steps": [
            "discover-desktop-state",
            "open-or-focus-app",
            "read-foreground-ui",
        ],
        "expected_request_tools": [
            "desktop.list_apps",
            "app.open",
            "desktop.ui_elements",
        ],
    },
    {
        "id": "capability_app_discovery_open",
        "prompt": "找一个能编辑 PDF 的本机应用并打开它",
        "allowed_tools": [
            "desktop.list_apps",
            "app.open",
        ],
        "expected_app": "pdf",
        "expected_steps": [
            "discover_apps-desktop-state",
            "open-selected-discovered-app",
        ],
        "expected_request_tools": [
            "desktop.list_apps",
            "app.open",
        ],
        "expected_model_followup": False,
    },
    {
        "id": "app_scoped_click",
        "prompt": "在 Notion 点击 New Page",
        "allowed_tools": [
            "desktop.inspect_app",
            "desktop.list_apps",
            "app.focus_and_click_ui_element",
            "desktop.ui_elements",
            "browser.click",
        ],
        "expected_app": "Notion",
        "expected_steps": [
            "inspect-app",
            "operate-foreground-ui",
            "verify-desktop-result",
        ],
        "expected_request_tools": [
            "desktop.inspect_app",
            "app.focus_and_click_ui_element",
            "desktop.ui_elements",
        ],
    },
    {
        "id": "app_scoped_type",
        "prompt": "在 Slack 的消息框输入 hello",
        "allowed_tools": [
            "desktop.inspect_app",
            "desktop.list_apps",
            "app.focus_and_type_into_ui_element",
            "desktop.ui_elements",
            "browser.type_text",
        ],
        "expected_app": "Slack",
        "expected_steps": [
            "inspect-app",
            "operate-foreground-ui",
            "verify-desktop-result",
        ],
        "expected_request_tools": [
            "desktop.inspect_app",
            "app.focus_and_type_into_ui_element",
            "desktop.ui_elements",
        ],
    },
    {
        "id": "app_scoped_hotkey",
        "prompt": "在 Notion 按 Command K",
        "allowed_tools": [
            "desktop.list_apps",
            "app.focus",
            "desktop.hotkey",
            "desktop.click_ui_element",
            "desktop.ui_elements",
        ],
        "expected_app": "Notion",
        "expected_steps": [
            "discover-desktop-state",
            "open-or-focus-app",
            "operate-foreground-ui",
            "verify-desktop-result",
        ],
        "expected_request_tools": [
            "desktop.list_apps",
            "app.focus",
            "desktop.hotkey",
            "desktop.ui_elements",
        ],
    },
    {
        "id": "app_scoped_safe_shortcut",
        "prompt": "在 Safari 打开新标签页",
        "allowed_tools": [
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.safe_shortcut",
            "desktop.ui_elements",
        ],
        "expected_app": "Safari",
        "expected_steps": [
            "discover-desktop-state",
            "operate-foreground-ui",
            "verify-desktop-result",
        ],
        "expected_request_tools": [
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.ui_elements",
        ],
    },
    {
        "id": "app_scoped_safe_shortcut_with_inspect",
        "prompt": "在 PixelForge 打开新标签页",
        "allowed_tools": [
            "desktop.inspect_app",
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.safe_shortcut",
            "desktop.ui_elements",
        ],
        "expected_app": "PixelForge",
        "expected_steps": [
            "inspect-app",
            "operate-foreground-ui",
            "verify-desktop-result",
        ],
        "expected_request_tools": [
            "desktop.inspect_app",
            "app.focus_and_safe_shortcut",
            "desktop.ui_elements",
        ],
    },
    {
        "id": "app_window_focus",
        "prompt": "切到 Slack 的 General 窗口",
        "allowed_tools": [
            "desktop.list_apps",
            "desktop.windows",
            "app.focus_window",
            "desktop.active_window",
        ],
        "expected_app": "Slack",
        "expected_steps": [
            "discover-desktop-state",
            "list-app-windows",
            "focus-app-window",
            "verify-desktop-result",
        ],
        "expected_request_tools": [
            "desktop.list_apps",
            "desktop.windows",
            "app.focus_window",
            "desktop.active_window",
        ],
    },
)


def _step_summary(step: Any) -> dict[str, Any]:
    return {
        "id": str(getattr(step, "step_id", "") or ""),
        "tool": str(getattr(step, "tool_name", "") or ""),
        "status": str(getattr(step, "status", "") or ""),
        "action": str(getattr(step, "action", "") or ""),
        "input": dict(getattr(step, "input_preview", {}) or {}),
        "depends_on": list(getattr(step, "depends_on", []) or []),
        "approval_required": bool(getattr(step, "approval_required", False)),
    }


def _request_tools(requests: list[dict[str, Any]]) -> list[str]:
    return [str(request.get("tool") or "") for request in requests]


def _case_evidence(case: dict[str, Any]) -> dict[str, Any]:
    prompt = str(case["prompt"])
    allowed_tools = [str(tool) for tool in case["allowed_tools"]]
    decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
    requests = planner_tool_requests(prompt, allowed_tools)
    steps = [_step_summary(step) for step in decision.plan.tool_plan.steps]
    request_tools = _request_tools(requests)
    expected_app = str(case["expected_app"])
    expected_steps = [str(step_id) for step_id in case["expected_steps"]]
    expected_request_tools = [str(tool) for tool in case["expected_request_tools"]]
    expected_model_followup = bool(case.get("expected_model_followup", False))
    discovery_request = requests[0] if requests else {}
    operation_request = requests[1] if len(requests) > 1 else {}
    discovery_input = discovery_request.get("input") if isinstance(discovery_request, dict) else {}
    operation_input = operation_request.get("input") if isinstance(operation_request, dict) else {}
    expected_discovery_tool = expected_request_tools[0] if expected_request_tools else ""
    checks = {
        "intent_is_desktop_operation": decision.selected_intent.kind == "desktop_operation",
        "route_to_studio": decision.plan.route_to_studio is True,
        "steps_match": [step["id"] for step in steps] == expected_steps,
        "request_tools_match": request_tools == expected_request_tools,
        "starts_with_discovery": request_tools[:1] == [expected_discovery_tool],
        "discovery_query_matches": (
            isinstance(discovery_input, dict)
            and (
                discovery_input.get("query") == expected_app
                or discovery_input.get("app_name") == expected_app
            )
        ),
        "operation_app_matches": (
            expected_discovery_tool == "desktop.inspect_app"
            or expected_model_followup
            or (
                isinstance(operation_input, dict)
                and operation_input.get("app_name") == expected_app
            )
            or (
                isinstance(operation_input, dict)
                and operation_input.get("selection_source") == "desktop.list_apps"
                and operation_input.get("query") == expected_app
            )
        ),
        "model_followup_matches": (
            any(bool(request.get("continue_to_model")) for request in requests)
            == expected_model_followup
        ),
        "uses_no_browser_tool": not any(tool.startswith("browser.") for tool in request_tools),
        "missing_capabilities_empty": decision.plan.tool_plan.missing_capabilities == [],
    }
    return {
        "id": str(case["id"]),
        "ok": all(checks.values()),
        "prompt": prompt,
        "intent_kind": decision.selected_intent.kind,
        "intent_inputs": decision.selected_intent.inputs,
        "required_capabilities": decision.plan.tool_plan.required_capabilities,
        "missing_capabilities": decision.plan.tool_plan.missing_capabilities,
        "route_to_studio": decision.plan.route_to_studio,
        "steps": steps,
        "requests": requests,
        "checks": checks,
    }


def run_smoke() -> dict[str, Any]:
    cases = [_case_evidence(case) for case in DESKTOP_PLANNER_CASES]
    return {
        "ok": all(case["ok"] for case in cases),
        "mode": "desktop_planner_discovery_smoke",
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
        print(f"desktop planner discovery smoke report: {args.report_json}", file=sys.stderr)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
