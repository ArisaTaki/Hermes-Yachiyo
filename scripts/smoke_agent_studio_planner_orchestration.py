#!/usr/bin/env python3
"""Smoke-test Agent Studio planner orchestration start boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.yachiyo_agent import AgentStudioService


class _FakeStudioPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def list_tool_catalog(self) -> dict[str, Any]:
        self.calls.append(("list_tool_catalog", None))
        return {
            "source": "agent_studio_planner_orchestration_smoke",
            "tools": [
                {
                    "tool_name": "workflow.run",
                    "function_name": "workflow_run",
                    "description": "Start a Workflow from Agent Studio.",
                    "capability_id": "workflow_orchestration",
                    "risk_level": "low",
                    "approval_required": False,
                },
                {
                    "tool_name": "group.run",
                    "function_name": "group_run",
                    "description": "Start an Agent GroupRun from Agent Studio.",
                    "capability_id": "multi_agent",
                    "risk_level": "low",
                    "approval_required": False,
                },
            ],
            "capabilities": {
                "workflow_orchestration": {
                    "available": True,
                    "tools": ["workflow.run"],
                    "risk_default": "low",
                },
                "multi_agent": {
                    "available": True,
                    "tools": ["group.run"],
                    "risk_default": "low",
                },
            },
        }

    def list_workflows(self) -> dict[str, Any]:
        self.calls.append(("list_workflows", None))
        return {
            "workflows": [
                {
                    "workflow_id": "workflow-review",
                    "name": "Review workflow",
                    "description": "Planner smoke workflow.",
                    "nodes": [{"id": "start", "type": "start"}],
                    "edges": [],
                    "enabled": True,
                }
            ]
        }

    def start_workflow_run(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_workflow_run", dict(request)))
        run_id = "run-studio-planner-workflow"
        return {
            "run_id": run_id,
            "workflow_run_id": "workflow-run-studio-planner",
            "workflow_id": request.get("workflow_id"),
            "status": "completed",
            "title": request.get("title") or "Review workflow",
            "objective": request.get("objective") or "",
            "events": [
                {
                    "event_id": "event-studio-planner-workflow-started",
                    "run_id": run_id,
                    "sequence": 1,
                    "event_type": "workflow.run.started",
                    "title": "Workflow run started",
                    "payload": {"metadata": request.get("metadata") or {}},
                }
            ],
            "created_at": "2026-07-01T00:00:00Z",
            "updated_at": "2026-07-01T00:00:01Z",
        }

    def list_groups(self) -> dict[str, Any]:
        self.calls.append(("list_groups", None))
        return {
            "groups": [
                {
                    "group_id": "group-research",
                    "name": "Research Team",
                    "description": "Planner smoke group.",
                    "members": [
                        {"agent_id": "agent-researcher", "name": "Researcher"},
                        {"agent_id": "agent-writer", "name": "Writer"},
                    ],
                    "mode": "moderated",
                    "enabled": True,
                }
            ]
        }

    def start_group_run(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_group_run", dict(request)))
        return {
            "group_run_id": "group-run-studio-planner",
            "run_group_id": "run-group-studio-planner",
            "group_id": request.get("group_id"),
            "title": request.get("title") or "Research Team",
            "status": "completed",
            "objective": request.get("objective") or "",
            "participants": [
                {"agent_id": "agent-researcher", "name": "Researcher"},
                {"agent_id": "agent-writer", "name": "Writer"},
            ],
            "events": [
                {
                    "event_id": "event-studio-planner-group-started",
                    "run_id": "group-run-studio-planner",
                    "sequence": 1,
                    "event_type": "group.run.started",
                    "title": "GroupRun started",
                    "payload": {"metadata": request.get("metadata") or {}},
                }
            ],
            "child_run_ids": ["run-researcher", "run-writer"],
            "final_answer": "GroupRun completed from planner orchestration.",
            "created_at": "2026-07-01T00:00:00Z",
            "updated_at": "2026-07-01T00:00:01Z",
        }


def _call_names(calls: Sequence[tuple[str, Any]]) -> list[str]:
    return [name for name, _payload in calls]


def _event_types(events: Sequence[Any]) -> list[str]:
    return [
        str(
            getattr(event, "event_type", "")
            or (event.get("event_type") if isinstance(event, dict) else "")
            or ""
        )
        for event in events
        if event
    ]


def _snapshot_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, dict) else {}


def _task_core_summary(task_core: Any) -> dict[str, Any]:
    payload = _snapshot_payload(task_core)
    workspace = payload.get("workspace")
    workspace = workspace if isinstance(workspace, dict) else {}
    workspace_items = workspace.get("items")
    workspace_items = workspace_items if isinstance(workspace_items, list) else []
    todos = payload.get("todos")
    todos = todos if isinstance(todos, list) else []
    checkpoints = payload.get("checkpoints")
    checkpoints = checkpoints if isinstance(checkpoints, list) else []
    replan_signals = payload.get("replan_signals")
    replan_signals = replan_signals if isinstance(replan_signals, list) else []
    return {
        "core_id": str(payload.get("core_id") or ""),
        "workspace_id": str(workspace.get("workspace_id") or ""),
        "workspace_item_count": len(workspace_items),
        "todo_step_ids": [
            str(item.get("step_id") or "")
            for item in todos
            if isinstance(item, dict) and str(item.get("step_id") or "").strip()
        ],
        "checkpoint_step_ids": [
            str(item.get("after_step_id") or "")
            for item in checkpoints
            if isinstance(item, dict) and str(item.get("after_step_id") or "").strip()
        ],
        "replan_checkpoint_step_ids": [
            str(item.get("after_step_id") or "")
            for item in checkpoints
            if (
                isinstance(item, dict)
                and item.get("replan_on_failure") is True
                and str(item.get("after_step_id") or "").strip()
            )
        ],
        "replan_triggers": [
            str(item.get("trigger") or "")
            for item in replan_signals
            if isinstance(item, dict) and str(item.get("trigger") or "").strip()
        ],
    }


def _task_core_checks(
    summary: dict[str, Any],
    *,
    expected_step_id: str,
) -> dict[str, bool]:
    todo_step_ids = set(summary.get("todo_step_ids") or [])
    checkpoint_step_ids = set(summary.get("checkpoint_step_ids") or [])
    replan_checkpoint_step_ids = set(summary.get("replan_checkpoint_step_ids") or [])
    return {
        "task_core_projected": bool(summary.get("core_id")),
        "task_core_has_workspace": bool(summary.get("workspace_id")),
        "task_core_has_workspace_items": (
            int(summary.get("workspace_item_count") or 0) > 0
        ),
        "task_core_has_todo": expected_step_id in todo_step_ids,
        "task_core_has_checkpoint": expected_step_id in checkpoint_step_ids,
        "task_core_replan_enabled": expected_step_id in replan_checkpoint_step_ids,
    }


def _run_workflow_case(service: AgentStudioService, port: _FakeStudioPort) -> dict[str, Any]:
    before = len(port.calls)
    result = service.start_planner_orchestration(
        {
            "prompt": "Run Review workflow",
            "target_name": "Review workflow",
            "objective": "Build report",
            "title": "Run Review workflow",
            "client_run_id": "smoke-studio-planner-workflow",
            "metadata": {"surface": "agent_studio"},
        }
    )
    snapshot = result.model_dump(mode="json")
    calls = port.calls[before:]
    start_calls = [payload for name, payload in calls if name == "start_workflow_run"]
    metadata = start_calls[0].get("metadata") if start_calls else {}
    task_core_summary = _task_core_summary(result.decision.plan.task_core)
    metadata_task_core_summary = _task_core_summary(metadata.get("yachiyo_task_core"))
    workflow_event_types = _event_types(
        result.workflow_run.events if result.workflow_run else []
    )
    expected_step_id = "workflow-orchestration"
    checks = {
        "started": result.status == "started",
        "kind_workflow": result.kind == "workflow",
        "intent_kind": result.decision.selected_intent.kind == "workflow_orchestration",
        "route_to_studio": result.route_to_studio is True,
        "target_resolved": result.target_id == "workflow-review",
        "workflow_run_returned": (
            result.workflow_run is not None
            and result.workflow_run.workflow_run_id == "workflow-run-studio-planner"
        ),
        "group_run_absent": result.group_run is None,
        "metadata_marks_orchestration": metadata.get("planner_orchestration") is True,
        "metadata_preserves_decision": (
            metadata.get("decision_id") == result.decision.decision_id
            and metadata.get("plan_id") == result.decision.plan.plan_id
        ),
        "metadata_preserves_task_core": (
            metadata_task_core_summary["core_id"] == task_core_summary["core_id"]
        ),
        "workflow_task_core_events_projected": all(
            event_type in workflow_event_types
            for event_type in (
                "workflow.run.task_core.created",
                "workflow.run.task.todo.updated",
                "workflow.run.task.checkpoint.updated",
            )
        ),
        **_task_core_checks(task_core_summary, expected_step_id=expected_step_id),
    }
    return {
        "id": "workflow_orchestration_start",
        "ok": all(checks.values()),
        "checks": checks,
        "call_names": _call_names(calls),
        "status": result.status,
        "kind": result.kind,
        "target_id": result.target_id,
        "run_id": snapshot.get("workflow_run", {}).get("run_id"),
        "workflow_run_id": snapshot.get("workflow_run", {}).get("workflow_run_id"),
        "decision_id": result.decision.decision_id,
        "plan_id": result.decision.plan.plan_id,
        "intent_kind": result.decision.selected_intent.kind,
        "event_types": workflow_event_types,
        "task_core_summary": task_core_summary,
        "metadata_task_core_summary": metadata_task_core_summary,
    }


def _run_group_case(service: AgentStudioService, port: _FakeStudioPort) -> dict[str, Any]:
    before = len(port.calls)
    result = service.start_planner_orchestration(
        {
            "prompt": "Run Research Team group to research Hanako",
            "target_name": "Research Team",
            "objective": "Research Hanako",
            "title": "Research Team GroupRun",
            "client_run_id": "smoke-studio-planner-group",
            "metadata": {"surface": "agent_studio"},
        }
    )
    snapshot = result.model_dump(mode="json")
    calls = port.calls[before:]
    start_calls = [payload for name, payload in calls if name == "start_group_run"]
    metadata = start_calls[0].get("metadata") if start_calls else {}
    task_core_summary = _task_core_summary(result.decision.plan.task_core)
    metadata_task_core_summary = _task_core_summary(metadata.get("yachiyo_task_core"))
    group_event_types = _event_types(
        result.group_run.events if result.group_run else []
    )
    expected_step_id = "group-multi_agent"
    checks = {
        "started": result.status == "started",
        "kind_group_run": result.kind == "group_run",
        "intent_kind": result.decision.selected_intent.kind == "multi_agent",
        "route_to_studio": result.route_to_studio is True,
        "target_resolved": result.target_id == "group-research",
        "group_run_returned": (
            result.group_run is not None
            and result.group_run.group_run_id == "group-run-studio-planner"
        ),
        "workflow_run_absent": result.workflow_run is None,
        "metadata_marks_orchestration": metadata.get("planner_orchestration") is True,
        "metadata_preserves_decision": (
            metadata.get("decision_id") == result.decision.decision_id
            and metadata.get("plan_id") == result.decision.plan.plan_id
        ),
        "metadata_preserves_task_core": (
            metadata_task_core_summary["core_id"] == task_core_summary["core_id"]
        ),
        "group_task_core_events_projected": all(
            event_type in group_event_types
            for event_type in (
                "group.run.task_core.created",
                "group.run.task.todo.updated",
                "group.run.task.checkpoint.updated",
            )
        ),
        **_task_core_checks(task_core_summary, expected_step_id=expected_step_id),
    }
    return {
        "id": "group_run_orchestration_start",
        "ok": all(checks.values()),
        "checks": checks,
        "call_names": _call_names(calls),
        "status": result.status,
        "kind": result.kind,
        "target_id": result.target_id,
        "group_run_id": snapshot.get("group_run", {}).get("group_run_id"),
        "run_group_id": snapshot.get("group_run", {}).get("run_group_id"),
        "decision_id": result.decision.decision_id,
        "plan_id": result.decision.plan.plan_id,
        "intent_kind": result.decision.selected_intent.kind,
        "event_types": group_event_types,
        "task_core_summary": task_core_summary,
        "metadata_task_core_summary": metadata_task_core_summary,
    }


def _run_missing_target_case(
    service: AgentStudioService,
    port: _FakeStudioPort,
) -> dict[str, Any]:
    before = len(port.calls)
    result = service.start_planner_orchestration(
        {
            "prompt": "Run Missing workflow",
            "target_name": "Missing workflow",
            "metadata": {"surface": "agent_studio"},
        }
    )
    calls = port.calls[before:]
    call_names = _call_names(calls)
    task_core_summary = _task_core_summary(result.decision.plan.task_core)
    checks = {
        "target_not_found": result.status == "target_not_found",
        "kind_workflow": result.kind == "workflow",
        "intent_kind": result.decision.selected_intent.kind == "workflow_orchestration",
        "target_name_preserved": result.target_name == "Missing workflow",
        "no_workflow_run": result.workflow_run is None,
        "no_group_run": result.group_run is None,
        "did_not_start_workflow": "start_workflow_run" not in call_names,
        "did_not_start_group": "start_group_run" not in call_names,
        **_task_core_checks(
            task_core_summary,
            expected_step_id="workflow-orchestration",
        ),
    }
    return {
        "id": "missing_target_handoff",
        "ok": all(checks.values()),
        "checks": checks,
        "call_names": call_names,
        "status": result.status,
        "kind": result.kind,
        "target_name": result.target_name,
        "decision_id": result.decision.decision_id,
        "plan_id": result.decision.plan.plan_id,
        "intent_kind": result.decision.selected_intent.kind,
        "message": result.message,
        "task_core_summary": task_core_summary,
    }


def run_smoke() -> dict[str, Any]:
    port = _FakeStudioPort()
    service = AgentStudioService(port)
    cases = [
        _run_workflow_case(service, port),
        _run_group_case(service, port),
        _run_missing_target_case(service, port),
    ]
    failed = [case for case in cases if case.get("ok") is not True]
    return {
        "ok": not failed,
        "mode": "agent_studio_planner_orchestration_smoke",
        "cases": cases,
        "call_names": _call_names(port.calls),
        "started_workflow_run_id": cases[0].get("workflow_run_id"),
        "started_group_run_id": cases[1].get("group_run_id"),
        "error": (
            f"{len(failed)} Agent Studio planner orchestration case(s) failed"
            if failed
            else ""
        ),
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", type=Path, help="Write full smoke evidence to JSON.")
    args = parser.parse_args(argv)

    summary = run_smoke()
    if args.report_json:
        _write_report(args.report_json, summary)
        print(f"agent studio planner orchestration smoke report: {args.report_json}")
    else:
        status = "passed" if summary.get("ok") is True else "failed"
        print(f"agent studio planner orchestration smoke: {status}")
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
