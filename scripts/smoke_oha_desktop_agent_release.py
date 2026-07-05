#!/usr/bin/env python3
"""Aggregate release smoke for Oha-Yachiyo desktop-agent product readiness."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.yachiyo_agent import RuntimePlanner
from apps.shell.yachiyo_agent.daily_desktop import (
    daily_desktop_allowed_tools,
    planner_first_daily_desktop_entrypoint_requests,
)
from apps.shell.yachiyo_agent.tool_catalog import runtime_tool_catalog_snapshot
from scripts import smoke_agent_entrypoint_desktop_execution
from scripts import smoke_agent_studio_planner_orchestration
from scripts import smoke_approval_policy_gate
from scripts import smoke_data_analysis_artifacts
from scripts import smoke_group_run_timeline
from scripts import smoke_planner_runtime_tool_parity
from scripts import smoke_workflow_run_timeline

SmokeRunner = Callable[[], dict[str, Any]]


def _tools(requests: Sequence[dict[str, Any]]) -> list[str]:
    return [
        str(request.get("tool") or "").strip()
        for request in requests
        if isinstance(request, dict) and str(request.get("tool") or "").strip()
    ]


def _sources(requests: Sequence[dict[str, Any]]) -> list[str]:
    return [
        str(request.get("source") or "").strip()
        for request in requests
        if isinstance(request, dict) and str(request.get("source") or "").strip()
    ]


def _deepagent_core_case() -> dict[str, Any]:
    decision = RuntimePlanner().decision(
        "打开 PixelForge",
        allowed_tools=daily_desktop_allowed_tools(),
    )
    plan = decision.plan
    tool_plan = plan.tool_plan
    task_core = plan.task_core
    checks = {
        "intent_is_desktop_operation": decision.selected_intent.kind == "desktop_operation",
        "tool_plan_has_discover_operate_verify": [
            step.tool_name for step in tool_plan.steps
        ]
        == ["desktop.list_apps", "app.open", "desktop.active_window"],
        "task_core_exists": bool(task_core.core_id),
        "workspace_exists": bool(task_core.workspace.workspace_id),
        "todos_cover_steps": [todo.step_id for todo in task_core.todos]
        == [step.step_id for step in tool_plan.steps],
        "checkpoints_cover_steps": [checkpoint.after_step_id for checkpoint in task_core.checkpoints]
        == [step.step_id for step in tool_plan.steps],
        "replan_signals_cover_steps": [signal.source_step_id for signal in task_core.replan_signals]
        == [step.step_id for step in tool_plan.steps],
    }
    return {
        "id": "deepagent_task_core",
        "ok": all(checks.values()),
        "intent_kind": decision.selected_intent.kind,
        "plan_id": plan.plan_id,
        "tool_plan_id": tool_plan.plan_id,
        "core_id": task_core.core_id,
        "workspace_id": task_core.workspace.workspace_id,
        "tool_steps": [step.tool_name for step in tool_plan.steps],
        "todo_step_ids": [todo.step_id for todo in task_core.todos],
        "checkpoint_step_ids": [checkpoint.after_step_id for checkpoint in task_core.checkpoints],
        "replan_step_ids": [signal.source_step_id for signal in task_core.replan_signals],
        "checks": checks,
    }


def _shared_surface_case() -> dict[str, Any]:
    surface_metadata = {
        "chat": {"surface": "chat_window"},
        "bubble": {
            "source": "launcher",
            "launcher_mode": "bubble",
            "launcher_surface": "quick_message",
        },
        "live2d": {
            "source": "launcher",
            "launcher_mode": "live2d",
            "launcher_surface": "live2d",
        },
    }
    cases: list[dict[str, Any]] = []
    for surface, metadata in surface_metadata.items():
        requests = planner_first_daily_desktop_entrypoint_requests(
            "打开 PixelForge",
            metadata=metadata,
            execution_normalized=True,
            include_runtime_context=True,
        )
        cases.append(
            {
                "surface": surface,
                "tools": _tools(requests),
                "sources": _sources(requests),
                "planning_reasons": [
                    str(request.get("planning_reason") or "").strip()
                    for request in requests
                    if isinstance(request, dict)
                ],
            }
        )
    checks = {
        "all_surfaces_present": [case["surface"] for case in cases]
        == ["chat", "bubble", "live2d"],
        "all_use_runtime_planner": all(
            case["sources"] and set(case["sources"]) == {"runtime_planner"}
            for case in cases
        ),
        "all_share_discover_operate_verify_tools": all(
            case["tools"] == ["desktop.list_apps", "app.open", "desktop.active_window"]
            for case in cases
        ),
        "no_legacy_surface_fallback": all(
            "daily_desktop_intent" not in case["sources"] for case in cases
        ),
    }
    return {
        "id": "chat_bubble_live2d_shared_runtime",
        "ok": all(checks.values()),
        "cases": cases,
        "checks": checks,
    }


def _tool_catalog_case() -> dict[str, Any]:
    catalog = runtime_tool_catalog_snapshot()
    tool_names = {tool.tool_name for tool in catalog.tools}
    coverage = catalog.legacy_cleanup_coverage
    checks = {
        "desktop_discovery_tools_visible": {
            "desktop.list_apps",
            "app.open",
            "desktop.active_window",
        }.issubset(tool_names),
        "approval_tools_visible": {
            "app.focus_and_click_ui_element",
            "app.focus_and_type_into_ui_element",
        }.issubset(tool_names),
        "legacy_cleanup_coverage_visible": coverage is not None,
        "cleanup_owned_by_runtime_planner": bool(coverage)
        and coverage.planner_owner == "runtime_planner",
        "cleanup_has_release_sized_sample_set": bool(coverage)
        and coverage.total_samples >= 57,
        "cleanup_tracks_app_launch": bool(coverage)
        and int(coverage.areas.get("app_launch", 0)) > 0,
    }
    return {
        "id": "studio_tool_catalog_runtime_coverage",
        "ok": all(checks.values()),
        "tool_count": len(tool_names),
        "coverage": coverage.model_dump(mode="json") if coverage else None,
        "checks": checks,
    }


def _run_section(
    section_id: str,
    objective: str,
    runner: SmokeRunner,
) -> dict[str, Any]:
    try:
        report = runner()
    except Exception as exc:
        return {
            "id": section_id,
            "objective": objective,
            "ok": False,
            "mode": "",
            "error": str(exc),
        }
    return {
        "id": section_id,
        "objective": objective,
        "ok": report.get("ok") is True,
        "mode": str(report.get("mode") or section_id),
        "report": report,
    }


def _build_sections(workdir: Path) -> list[dict[str, Any]]:
    return [
        _run_section(
            "deepagent_core",
            "Task workspace, todo, checkpoint, and replan signals exist for desktop plans.",
            _deepagent_core_case,
        ),
        _run_section(
            "shared_daily_surfaces",
            "Chat, Bubble, and Live2D share the runtime planner entrypoint.",
            _shared_surface_case,
        ),
        _run_section(
            "desktop_executor_before_model",
            "Desktop discover/operate/verify runs before model fallback.",
            lambda: smoke_agent_entrypoint_desktop_execution.run_smoke(
                workdir=workdir / "desktop-entrypoint"
            ),
        ),
        _run_section(
            "capability_planner_tool_parity",
            "Runtime planner tool plans map to registered executable tools and approval policy.",
            smoke_planner_runtime_tool_parity.run_smoke,
        ),
        _run_section(
            "data_analysis_artifacts",
            "Data analysis handles CSV, JSON, text tables, XLSX, and produces artifacts.",
            lambda: smoke_data_analysis_artifacts.run_smoke(workdir / "data-analysis"),
        ),
        _run_section(
            "agent_studio_orchestration",
            "Agent Studio starts Workflow and GroupRun through the shared planner.",
            smoke_agent_studio_planner_orchestration.run_smoke,
        ),
        _run_section(
            "group_run_timeline",
            "GroupRun timeline preserves participant, approval, artifact, and event context.",
            smoke_group_run_timeline.run_smoke,
        ),
        _run_section(
            "workflow_run_timeline",
            "WorkflowRun timeline preserves child run, approval, artifact, and event context.",
            smoke_workflow_run_timeline.run_smoke,
        ),
        _run_section(
            "approval_policy_gate",
            "Approval and policy gates remain enforced for higher-risk desktop actions.",
            smoke_approval_policy_gate.run_smoke,
        ),
        _run_section(
            "studio_tool_catalog",
            "Agent Studio sees runtime tools and legacy-cleanup coverage.",
            _tool_catalog_case,
        ),
    ]


def run_smoke(*, workdir: Path | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="oha-desktop-agent-release-smoke-") as temp_dir:
        root = Path(workdir) if workdir is not None else Path(temp_dir)
        root.mkdir(parents=True, exist_ok=True)
        sections = _build_sections(root)
    failed = [section for section in sections if section.get("ok") is not True]
    checks = {
        "all_sections_passed": not failed,
        "covers_deepagent_core": any(section["id"] == "deepagent_core" for section in sections),
        "covers_desktop_executor": any(
            section["id"] == "desktop_executor_before_model" for section in sections
        ),
        "covers_chat_bubble_live2d": any(
            section["id"] == "shared_daily_surfaces" for section in sections
        ),
        "covers_agent_studio": any(
            section["id"] == "agent_studio_orchestration" for section in sections
        ),
        "covers_groups_workflow": {
            "group_run_timeline",
            "workflow_run_timeline",
        }.issubset({str(section["id"]) for section in sections}),
        "covers_approval_gate": any(
            section["id"] == "approval_policy_gate" for section in sections
        ),
        "covers_data_analysis": any(
            section["id"] == "data_analysis_artifacts" for section in sections
        ),
        "covers_studio_debug_catalog": any(
            section["id"] == "studio_tool_catalog" for section in sections
        ),
    }
    return {
        "ok": all(checks.values()),
        "mode": "oha_desktop_agent_release_smoke",
        "section_count": len(sections),
        "failed_sections": [str(section["id"]) for section in failed],
        "checks": checks,
        "sections": sections,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir",
        type=Path,
        help="Optional persistent workspace for smoke-generated files.",
    )
    parser.add_argument("--report-json", type=Path, help="Optional JSON evidence report path.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = run_smoke(workdir=args.workdir)
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
        print(f"oha desktop agent release smoke report: {args.report_json}", file=sys.stderr)
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
