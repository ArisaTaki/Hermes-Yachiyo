#!/usr/bin/env python3
"""Smoke-test approval and policy gates for planner-facing tool plans."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.agent.tools.policy import PolicyGate, RuntimePolicyCompiler
from apps.shell.yachiyo_agent import RuntimePlanner
from apps.shell.yachiyo_agent.planner_execution import planner_tool_requests
from apps.shell.yachiyo_agent.policy import group_tool_policy_for_id

PLANNER_APPROVAL_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "low_risk_app_open",
        "prompt": "打开 PixelForge",
        "allowed_tools": ["desktop.list_apps", "app.open", "desktop.active_window"],
        "expected_intent": "desktop_operation",
        "expected_tools": ["desktop.list_apps", "app.open", "desktop.active_window"],
        "expected_approval_steps": [],
        "expected_low_risk_tools": ["desktop.list_apps", "app.open", "desktop.active_window"],
    },
    {
        "id": "low_risk_current_page_report",
        "prompt": "把当前网页总结成一份报告",
        "allowed_tools": ["browser.current_page", "browser.extract_text", "artifact.write"],
        "expected_intent": "web_research",
        "expected_tools": ["browser.extract_text"],
        "expected_approval_steps": [],
        "expected_low_risk_tools": ["browser.extract_text", "artifact.write"],
    },
    {
        "id": "medium_risk_app_click",
        "prompt": "在 Notion 点击 New Page",
        "allowed_tools": [
            "desktop.list_apps",
            "app.focus_and_click_ui_element",
            "desktop.ui_elements",
            "browser.click",
        ],
        "expected_intent": "desktop_operation",
        "expected_tools": [
            "desktop.list_apps",
            "app.focus_and_click_ui_element",
            "desktop.ui_elements",
        ],
        "expected_approval_steps": ["operate-foreground-ui"],
        "expected_approval_tools": ["app.focus_and_click_ui_element"],
    },
    {
        "id": "medium_risk_app_type",
        "prompt": "在 Slack 的消息框输入 hello",
        "allowed_tools": [
            "desktop.list_apps",
            "app.focus_and_type_into_ui_element",
            "desktop.ui_elements",
            "browser.type_text",
        ],
        "expected_intent": "desktop_operation",
        "expected_tools": [
            "desktop.list_apps",
            "app.focus_and_type_into_ui_element",
            "desktop.ui_elements",
        ],
        "expected_approval_steps": ["operate-foreground-ui"],
        "expected_approval_tools": ["app.focus_and_type_into_ui_element"],
    },
    {
        "id": "medium_risk_browser_click",
        "prompt": "在浏览器点击登录按钮",
        "allowed_tools": ["browser.click", "browser.current_page"],
        "expected_intent": "web_research",
        "expected_tools": ["browser.click"],
        "expected_approval_steps": ["click-current-page-element"],
        "expected_approval_tools": ["browser.click"],
    },
)


def _step_summary(step: Any) -> dict[str, Any]:
    return {
        "id": str(getattr(step, "step_id", "") or ""),
        "tool": str(getattr(step, "tool_name", "") or ""),
        "status": str(getattr(step, "status", "") or ""),
        "action": str(getattr(step, "action", "") or ""),
        "risk_level": str(getattr(step, "risk_level", "") or ""),
        "approval_required": bool(getattr(step, "approval_required", False)),
        "input": dict(getattr(step, "input_preview", {}) or {}),
        "depends_on": list(getattr(step, "depends_on", []) or []),
    }


def _request_tools(requests: list[dict[str, Any]]) -> list[str]:
    return [str(request.get("tool") or "") for request in requests]


def _planner_case_evidence(case: dict[str, Any]) -> dict[str, Any]:
    prompt = str(case["prompt"])
    allowed_tools = [str(tool) for tool in case["allowed_tools"]]
    decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
    requests = planner_tool_requests(prompt, allowed_tools)
    steps = [_step_summary(step) for step in decision.plan.tool_plan.steps]
    step_by_tool = {step["tool"]: step for step in steps if step["tool"]}
    expected_tools = [str(tool) for tool in case["expected_tools"]]
    expected_approval_steps = [str(step_id) for step_id in case["expected_approval_steps"]]
    expected_approval_tools = [str(tool) for tool in case.get("expected_approval_tools", [])]
    expected_low_risk_tools = [str(tool) for tool in case.get("expected_low_risk_tools", [])]
    approval_steps = list(decision.plan.tool_plan.approvals_required)
    checks = {
        "intent_matches": decision.selected_intent.kind == str(case["expected_intent"]),
        "request_tools_match": _request_tools(requests) == expected_tools,
        "approval_steps_match": approval_steps == expected_approval_steps,
        "approval_tools_marked": all(
            step_by_tool.get(tool, {}).get("approval_required") is True
            and step_by_tool.get(tool, {}).get("risk_level") in {"medium", "high"}
            for tool in expected_approval_tools
        ),
        "low_risk_tools_not_marked": all(
            step_by_tool.get(tool, {}).get("approval_required") is False
            and step_by_tool.get(tool, {}).get("risk_level") == "low"
            for tool in expected_low_risk_tools
            if tool in step_by_tool
        ),
        "no_unexpected_approvals": {
            step["id"] for step in steps if step["approval_required"]
        }
        == set(expected_approval_steps),
    }
    return {
        "id": str(case["id"]),
        "ok": all(checks.values()),
        "prompt": prompt,
        "intent_kind": decision.selected_intent.kind,
        "approvals_required": approval_steps,
        "steps": steps,
        "requests": requests,
        "checks": checks,
    }


def _runtime_policy_evidence() -> dict[str, Any]:
    compiler = RuntimePolicyCompiler()
    compiled = compiler.compile_tool_policy(
        "custom",
        {
            "allowed_tools": [
                "terminal.run",
                "workspace.read",
                "app.focus_and_click_ui_element",
                "browser.click",
                "app.open",
                "browser.extract_text",
            ],
            "approval_required": {
                "terminal.run": False,
            },
        },
    )
    approval_required = compiled["approval_required"]
    checks = {
        "terminal_run_forced_to_approval": approval_required.get("terminal.run") is True,
        "desktop_medium_forced_to_approval": approval_required.get(
            "app.focus_and_click_ui_element"
        )
        is True,
        "browser_medium_forced_to_approval": approval_required.get("browser.click") is True,
        "low_risk_app_open_not_forced": approval_required.get("app.open") is not True,
        "low_risk_browser_extract_not_forced": approval_required.get("browser.extract_text")
        is not True,
        "exact_allow_list_allows_known_tool": PolicyGate.allows_tool(
            "app.focus_and_click_ui_element",
            compiled["allowed_tools"],
        )
        is True,
        "exact_allow_list_blocks_missing_tool": PolicyGate.allows_tool(
            "workspace.write_patch",
            compiled["allowed_tools"],
        )
        is False,
    }
    return {
        "ok": all(checks.values()),
        "compiled": compiled,
        "checks": checks,
    }


def _group_policy_evidence() -> dict[str, Any]:
    policy = group_tool_policy_for_id("desktop_execution")
    allowed_tools = list(policy.get("allowed_tools") or [])
    approval_required = dict(policy.get("approval_required") or {})
    checks = {
        "allows_low_risk_open": "app.open" in allowed_tools,
        "low_risk_open_not_approval_required": approval_required.get("app.open")
        is not True,
        "desktop_click_requires_approval": approval_required.get(
            "app.focus_and_click_ui_element"
        )
        is True,
        "desktop_type_requires_approval": approval_required.get(
            "app.focus_and_type_into_ui_element"
        )
        is True,
        "browser_click_requires_approval": approval_required.get("browser.click") is True,
        "browser_type_requires_approval": approval_required.get("browser.type_text") is True,
        "submit_foreground_requires_approval": approval_required.get(
            "desktop.submit_foreground"
        )
        is True,
    }
    return {
        "ok": all(checks.values()),
        "allowed_tool_count": len(allowed_tools),
        "approval_required_tools": sorted(
            tool for tool, required in approval_required.items() if required
        ),
        "checks": checks,
    }


def run_smoke() -> dict[str, Any]:
    planner_cases = [_planner_case_evidence(case) for case in PLANNER_APPROVAL_CASES]
    runtime_policy = _runtime_policy_evidence()
    group_policy = _group_policy_evidence()
    return {
        "ok": all(case["ok"] for case in planner_cases)
        and runtime_policy["ok"]
        and group_policy["ok"],
        "mode": "approval_policy_gate_smoke",
        "planner_case_count": len(planner_cases),
        "planner_cases": planner_cases,
        "runtime_policy": runtime_policy,
        "group_policy": group_policy,
    }


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description=__doc__)


def main(argv: Sequence[str] | None = None) -> int:
    _parser().parse_args(argv)
    evidence = run_smoke()
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
