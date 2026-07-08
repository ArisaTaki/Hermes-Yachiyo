#!/usr/bin/env python3
"""Smoke-test that Agent entrypoints run data analysis and emit artifacts before model fallback."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import apps.shell.agent_runtime as agent_runtime_mod
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.yachiyo_agent.legacy_ports import LegacyStudioPort
from apps.shell.yachiyo_agent.studio_service import AgentStudioService

SAMPLE_CSV = "region,revenue,units\nEast,10,1\nWest,20,2\nEast,30,3\n"
SAMPLE_PATH = "inputs/sales.csv"
PROMPT = f"请分析 {SAMPLE_PATH} 并输出报告"
ARTIFACT_PATH = "analysis-report.md"


class _FakeDefaultProfileService:
    def get_defaults(self) -> dict[str, str]:
        return {"chat": "profile_default"}

    def get_profile_private(self, profile_id: str) -> dict[str, Any]:
        if profile_id != "profile_default":
            raise KeyError(profile_id)
        return {
            "profile_id": profile_id,
            "provider": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
            "capability": "chat",
            "status": "available",
            "enabled": True,
        }


@contextmanager
def _patched_attr(target: Any, name: str, value: Any) -> Iterator[None]:
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


def _make_service(root: Path) -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=root / "agent-runtime.db",
        workspace_dir=root / "runtime",
        credential_store=MemoryCredentialStore(),
    )


def _write_dataset(workdir: Path) -> None:
    target = workdir / SAMPLE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SAMPLE_CSV, encoding="utf-8")


def _workspace_policy(workdir: Path) -> dict[str, Any]:
    return {
        "default_workdir": str(workdir),
        "readable_scopes": ["."],
        "writable_scopes": ["."],
    }


def _event_types(events: Sequence[dict[str, Any]]) -> list[str]:
    return [str(event.get("event_type") or "") for event in events if isinstance(event, dict)]


def _events_of_type(events: Sequence[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if isinstance(event, dict) and event.get("event_type") == event_type
    ]


def _first_event(events: Sequence[dict[str, Any]], event_type: str) -> dict[str, Any]:
    for event in events:
        if isinstance(event, dict) and event.get("event_type") == event_type:
            return event
    return {}


def _first_tool_event(
    events: Sequence[dict[str, Any]],
    event_type: str,
    tool_name: str,
) -> dict[str, Any]:
    for event in events:
        if not isinstance(event, dict) or event.get("event_type") != event_type:
            continue
        if _payload(event).get("tool") == tool_name:
            return event
    return {}


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event, dict) else {}
    return payload if isinstance(payload, dict) else {}


def _model_event_free(events: Sequence[dict[str, Any]]) -> bool:
    return not any(
        event_type in {"model.request.started", "model.requested"}
        for event_type in _event_types(events)
    )


def _artifact_paths(artifacts: Any) -> list[str]:
    if not isinstance(artifacts, list):
        return []
    return [
        str(artifact.get("path") or "")
        for artifact in artifacts
        if isinstance(artifact, dict) and str(artifact.get("path") or "").strip()
    ]


def _task_core_from_payloads(
    updated: dict[str, Any],
    selection_event: dict[str, Any],
) -> dict[str, Any]:
    direct = updated.get("task_core")
    if isinstance(direct, dict) and direct:
        return direct
    payload = _payload(selection_event)
    for key in ("runtime_plan", "yachiyo_execution_envelope"):
        nested = payload.get(key)
        if isinstance(nested, dict) and isinstance(nested.get("task_core"), dict):
            return dict(nested["task_core"])
    studio_core = payload.get("yachiyo_task_core")
    return dict(studio_core) if isinstance(studio_core, dict) else {}


def _task_core_summary(task_core: dict[str, Any]) -> dict[str, Any]:
    workspace = task_core.get("workspace")
    workspace = workspace if isinstance(workspace, dict) else {}
    workspace_items = workspace.get("items")
    workspace_items = workspace_items if isinstance(workspace_items, list) else []
    todos = task_core.get("todos")
    todos = todos if isinstance(todos, list) else []
    checkpoints = task_core.get("checkpoints")
    checkpoints = checkpoints if isinstance(checkpoints, list) else []
    replan_signals = task_core.get("replan_signals")
    replan_signals = replan_signals if isinstance(replan_signals, list) else []
    return {
        "core_id": str(task_core.get("core_id") or ""),
        "workspace_id": str(workspace.get("workspace_id") or ""),
        "workspace_item_count": len(workspace_items),
        "workspace_paths": [
            str(item.get("path") or "")
            for item in workspace_items
            if isinstance(item, dict) and str(item.get("path") or "").strip()
        ],
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
        "replan_triggers": [
            str(item.get("trigger") or "")
            for item in replan_signals
            if isinstance(item, dict) and str(item.get("trigger") or "").strip()
        ],
    }


def _contains_all(values: Sequence[str], expected: Sequence[str]) -> bool:
    value_set = set(values)
    return all(value in value_set for value in expected)


def _data_analysis_case(
    service: AgentRuntimeService,
    *,
    entrypoint: str,
    workdir: Path,
) -> dict[str, Any]:
    policy = _workspace_policy(workdir)
    if entrypoint == "main_chat":
        run = service.start_main_chat_run(
            task_id="smoke-main-chat-data-analysis",
            session_id="smoke-main-chat-data-analysis-session",
            user_goal=PROMPT,
        )
        loop_result = service.execute_main_chat_model_loop(
            str(run["run_id"]),
            [{"role": "user", "content": PROMPT}],
            workspace_policy=policy,
        )
        updated = service.complete_main_chat_run(
            str(run["run_id"]),
            str(loop_result.get("result") or ""),
        )
        run_id = str(run.get("run_id") or "")
        loop_status = loop_result.get("status")
    else:
        agent = service.create_agent(
            {
                "name": f"Data Analysis Agent {entrypoint}",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {
                    "allowed_tools": ["workspace.read", "data.analyze", "artifact.write"],
                    "approval_required": {},
                },
                "workspace_policy": policy,
            }
        )
        if entrypoint == "studio_agent_run":
            snapshot = AgentStudioService(LegacyStudioPort(service)).start_agent_run(
                {
                    "agent_id": agent["agent_id"],
                    "objective": PROMPT,
                    "client_run_id": "smoke-studio-agent-data-analysis-run",
                }
            )
            updated = snapshot.model_dump(mode="json")
        elif entrypoint == "workflow_agent_node":
            workflow = service.create_workflow(
                {
                    "name": "Data Analysis Workflow Entrypoint",
                    "nodes": [
                        {"id": "start", "type": "start", "data": {"label": "Start"}},
                        {
                            "id": "analysis",
                            "type": "agent",
                            "data": {
                                "label": "Analyze",
                                "agent_id": agent["agent_id"],
                                "task": PROMPT,
                            },
                        },
                    ],
                    "edges": [{"source": "start", "target": "analysis"}],
                }
            )
            workflow_run = service.create_workflow_run(
                {
                    "workflow_id": workflow["workflow_id"],
                    "user_goal": PROMPT,
                }
            )
            group = service.get_run_group(str(workflow_run.get("run_group_id") or ""))
            child_run_ids = [
                str(child_run_id or "")
                for child_run_id in group.get("child_run_ids") or []
                if str(child_run_id or "") and str(child_run_id or "") != str(workflow_run.get("run_id") or "")
            ]
            updated = service.get_run(child_run_ids[0]) if child_run_ids else workflow_run
        else:
            updated = service.create_agent_run(
                {
                    "agent_id": agent["agent_id"],
                    "user_goal": PROMPT,
                    "runtime_planner_entrypoint": True,
                }
            )
        run_id = str(updated.get("run_id") or "")
        loop_status = ""

    events = service.list_run_events(run_id)["events"]
    planned_event = _first_tool_event(events, "agent.desktop.intent_planned", "data.analyze")
    read_planned_event = _first_tool_event(events, "agent.desktop.intent_planned", "workspace.read")
    tool_event = _first_tool_event(events, "agent.tool.call", "data.analyze")
    read_tool_event = _first_tool_event(events, "agent.tool.call", "workspace.read")
    completed_event = _first_event(events, "agent.desktop.intent_completed")
    selection_event = _first_event(events, "agent.plan.selection")
    artifact_events = [
        event
        for event in _events_of_type(events, "artifact.created")
        if _payload(event).get("path") == ARTIFACT_PATH
    ]
    tool_result = _payload(tool_event).get("result")
    tool_result = tool_result if isinstance(tool_result, dict) else {}
    completed_result = _payload(completed_event).get("result")
    completed_result = completed_result if isinstance(completed_result, dict) else {}
    artifacts = updated.get("artifacts")
    summary_text = str(updated.get("result") or _payload(completed_event).get("summary") or "")
    task_core = _task_core_from_payloads(updated, selection_event)
    task_core_summary = _task_core_summary(task_core)
    expected_step_ids = ["read-data-source", "analyze-data-file"]
    checks = {
        "run_completed": updated.get("status") == "completed",
        "summary_mentions_data_analysis": f"已分析「{SAMPLE_PATH}」（3 行、3 列）"
        in summary_text,
        "model_not_called": _model_event_free(events),
        "selection_is_data_analysis": _payload(selection_event).get("intent_kind") == "data_analysis",
        "selection_uses_runtime_planner_full_plan": _payload(selection_event).get("selection_reason")
        == "runtime_planner_full_plan_execution",
        "planned_workspace_read": _payload(read_planned_event).get("tool") == "workspace.read",
        "planned_data_analyze": _payload(planned_event).get("tool") == "data.analyze",
        "planned_input_path": (_payload(planned_event).get("input_preview") or {}).get("path")
        == SAMPLE_PATH,
        "tool_call_workspace_read": _payload(read_tool_event).get("tool") == "workspace.read",
        "tool_call_data_analyze": _payload(tool_event).get("tool") == "data.analyze",
        "tool_result_ok": tool_result.get("ok") is True,
        "tool_result_rows": tool_result.get("rows") == 3,
        "artifact_event_recorded": bool(artifact_events),
        "artifact_projection_recorded": ARTIFACT_PATH in _artifact_paths(artifacts),
        "completed_from_runtime_planner": _payload(completed_event).get("source") == "runtime_planner",
        "completed_artifact_path": completed_result.get("artifact_path") == ARTIFACT_PATH,
        "task_core_projected": bool(task_core),
        "task_core_has_workspace": bool(task_core_summary["workspace_id"]),
        "task_core_tracks_dataset_and_artifact": (
            SAMPLE_PATH in task_core_summary["workspace_paths"]
            and ARTIFACT_PATH in task_core_summary["workspace_paths"]
        ),
        "task_core_has_todo_steps": _contains_all(
            task_core_summary["todo_step_ids"],
            expected_step_ids,
        ),
        "task_core_has_checkpoints": _contains_all(
            task_core_summary["checkpoint_step_ids"],
            expected_step_ids,
        ),
        "task_core_has_replan_signal": bool(task_core_summary["replan_triggers"]),
    }
    return {
        "id": f"{entrypoint}_data_analysis_before_model",
        "ok": all(checks.values()),
        "run_id": run_id,
        "status": updated.get("status"),
        "loop_status": loop_status,
        "result": summary_text,
        "artifact_paths": _artifact_paths(artifacts),
        "event_types": _event_types(events),
        "selection_event": selection_event,
        "planned_event": planned_event,
        "read_planned_event": read_planned_event,
        "tool_event": tool_event,
        "read_tool_event": read_tool_event,
        "artifact_events": artifact_events,
        "completed_event": completed_event,
        "task_core_summary": task_core_summary,
        "checks": checks,
    }


def run_smoke(*, workdir: Path | None = None) -> dict[str, Any]:
    model_call_count = 0

    def forbidden_model_call(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        nonlocal model_call_count
        model_call_count += 1
        raise RuntimeError("data analysis entrypoint smoke should execute before model call")

    with tempfile.TemporaryDirectory(prefix="oha-entrypoint-data-smoke-") as temp_dir:
        root = Path(workdir) if workdir is not None else Path(temp_dir)
        root.mkdir(parents=True, exist_ok=True)
        data_workdir = root / "workdir"
        _write_dataset(data_workdir)
        service = _make_service(root)
        try:
            with _patched_attr(
                agent_runtime_mod,
                "get_model_profile_service",
                lambda: _FakeDefaultProfileService(),
            ), _patched_attr(
                agent_runtime_mod,
                "openai_compatible_chat_message",
                forbidden_model_call,
            ):
                cases = [
                    _data_analysis_case(service, entrypoint="main_chat", workdir=data_workdir),
                    _data_analysis_case(service, entrypoint="agent_run", workdir=data_workdir),
                    _data_analysis_case(
                        service,
                        entrypoint="studio_agent_run",
                        workdir=data_workdir,
                    ),
                    _data_analysis_case(
                        service,
                        entrypoint="workflow_agent_node",
                        workdir=data_workdir,
                    ),
                ]
        finally:
            service.close()
    checks = {
        "all_cases_passed": all(case.get("ok") is True for case in cases),
        "model_never_called": model_call_count == 0,
    }
    return {
        "ok": all(checks.values()),
        "mode": "agent_entrypoint_data_analysis_smoke",
        "case_count": len(cases),
        "model_call_count": model_call_count,
        "cases": cases,
        "checks": checks,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, help="Optional persistent smoke workdir.")
    parser.add_argument("--report-json", type=Path, help="Optional JSON evidence report path.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = run_smoke(workdir=args.workdir)
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
        print(f"agent entrypoint data analysis smoke report: {args.report_json}", file=sys.stderr)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
