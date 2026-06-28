#!/usr/bin/env python3
"""Smoke-test browser planner decisions and artifact expectations."""

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

BROWSER_PLANNER_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "current_page_report",
        "prompt": "把当前网页总结成一份报告",
        "allowed_tools": ["browser.current_page", "browser.extract_text", "artifact.write"],
        "expected_steps": ["extract-current-page-text", "write-research-artifact"],
        "expected_request_tool": "browser.extract_text",
        "expected_artifacts": ["research-summary.md"],
        "expect_continue_to_model": True,
    },
    {
        "id": "explicit_url_report",
        "prompt": "调研 https://example.com 的信息并写成报告",
        "allowed_tools": [
            "browser.open_url_and_extract_text",
            "browser.open_url",
            "browser.extract_text",
            "artifact.write",
        ],
        "expected_steps": ["open-or-read-web", "write-research-artifact"],
        "expected_request_tool": "browser.open_url_and_extract_text",
        "expected_artifacts": ["research-summary.md"],
        "expect_continue_to_model": True,
    },
    {
        "id": "current_page_screenshot",
        "prompt": "screenshot current webpage",
        "allowed_tools": ["browser.screenshot", "screen.capture"],
        "expected_steps": ["capture-current-page"],
        "expected_request_tool": "browser.screenshot",
        "expected_artifacts": ["browser/current-page.png"],
        "expect_continue_to_model": False,
    },
    {
        "id": "search_report",
        "prompt": "研究一下 OpenAI 最新新闻并输出报告",
        "allowed_tools": ["browser.open_url", "artifact.write"],
        "expected_steps": ["open-web-search", "write-research-artifact"],
        "expected_request_tool": "browser.open_url",
        "expected_artifacts": ["research-summary.md"],
        "expect_continue_to_model": True,
    },
)


def _step_summary(step: Any) -> dict[str, Any]:
    return {
        "id": str(getattr(step, "step_id", "") or ""),
        "tool": str(getattr(step, "tool_name", "") or ""),
        "status": str(getattr(step, "status", "") or ""),
        "action": str(getattr(step, "action", "") or ""),
        "input": dict(getattr(step, "input_preview", {}) or {}),
        "approval_required": bool(getattr(step, "approval_required", False)),
    }


def _case_evidence(case: dict[str, Any]) -> dict[str, Any]:
    prompt = str(case["prompt"])
    allowed_tools = [str(tool) for tool in case["allowed_tools"]]
    decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
    requests = planner_tool_requests(prompt, allowed_tools)
    steps = [_step_summary(step) for step in decision.plan.tool_plan.steps]
    request_tools = [str(request.get("tool") or "") for request in requests]
    browser_request_tools = [tool for tool in request_tools if tool.startswith("browser.")]
    artifacts_expected = list(decision.plan.tool_plan.artifacts_expected)
    expected_steps = [str(step_id) for step_id in case["expected_steps"]]
    expected_request_tool = str(case["expected_request_tool"])
    expected_artifacts = [str(path) for path in case["expected_artifacts"]]
    expected_continue = bool(case.get("expect_continue_to_model"))
    first_request = requests[0] if requests else {}
    has_artifact_write_step = any(step["tool"] == "artifact.write" for step in steps)
    checks = {
        "intent_is_web_research": decision.selected_intent.kind == "web_research",
        "steps_match": [step["id"] for step in steps] == expected_steps,
        "request_tool_matches": request_tools[:1] == [expected_request_tool],
        "uses_browser_tool": bool(browser_request_tools),
        "artifacts_match": artifacts_expected == expected_artifacts,
        "continue_to_model_matches": bool(first_request.get("continue_to_model"))
        == expected_continue,
    }
    if expected_artifacts and expected_artifacts != ["browser/current-page.png"]:
        checks["artifact_write_step_present"] = has_artifact_write_step
    return {
        "id": str(case["id"]),
        "ok": all(checks.values()),
        "prompt": prompt,
        "intent_kind": decision.selected_intent.kind,
        "intent_inputs": decision.selected_intent.inputs,
        "steps": steps,
        "requests": requests,
        "artifacts_expected": artifacts_expected,
        "checks": checks,
    }


def run_smoke() -> dict[str, Any]:
    cases = [_case_evidence(case) for case in BROWSER_PLANNER_CASES]
    ok = all(case["ok"] for case in cases)
    return {
        "ok": ok,
        "mode": "browser_planner_artifact_smoke",
        "case_count": len(cases),
        "cases": cases,
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
