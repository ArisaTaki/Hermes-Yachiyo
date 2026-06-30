#!/usr/bin/env python3
"""Smoke-test WorkflowRun public snapshots, replay events, and Studio calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.yachiyo_agent import AgentStudioService, StartWorkflowRunRequest

WORKFLOW_ID = "workflow-smoke"
WORKFLOW_RUN_ID = "workflow-run-smoke"
LISTED_WORKFLOW_RUN_ID = "workflow-run-listed"
CHILD_RUN_ID = "workflow-child-agent-smoke"
APPROVAL_ID = "approval-workflow-smoke"
ARTIFACT_PATH = "workflows/smoke-report.md"


class _FakeWorkflowRunPort:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def list_workflows(self) -> dict[str, Any]:
        self.calls.append({"name": "list_workflows"})
        return {"ok": True, "workflows": [_workflow_payload()]}

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        self.calls.append({"name": "get_workflow", "workflow_id": workflow_id})
        return _workflow_payload(workflow_id=workflow_id)

    def start_workflow_run(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"name": "start_workflow_run", "request": request})
        return _workflow_run_payload(
            run_id=WORKFLOW_RUN_ID,
            workflow_id=str(request.get("workflow_id") or WORKFLOW_ID),
            objective=str(request.get("objective") or ""),
            status="approval_required",
        )

    def list_run_timelines(self, limit: int = 50) -> dict[str, Any]:
        self.calls.append({"name": "list_run_timelines", "limit": limit})
        return {
            "ok": True,
            "runs": [
                _workflow_run_payload(
                    run_id=LISTED_WORKFLOW_RUN_ID,
                    status="completed",
                    final_answer="Listed Workflow run completed.",
                )
            ],
        }

    def get_run_timeline(self, run_id: str) -> dict[str, Any]:
        self.calls.append({"name": "get_run_timeline", "run_id": run_id})
        return _workflow_run_payload(run_id=run_id, status="approval_required")

    def get_run_event_stream(self, run_id: str) -> dict[str, Any]:
        self.calls.append({"name": "get_run_event_stream", "run_id": run_id})
        return {"ok": True, "events": _workflow_run_events(run_id)}

    def get_run_event_page(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "name": "get_run_event_page",
                "run_id": run_id,
                "after_sequence": after_sequence,
                "limit": limit,
            }
        )
        events = [
            event
            for event in _workflow_run_events(run_id)
            if int(event["sequence"]) > after_sequence
        ]
        page = events[:limit]
        return {
            "run_id": run_id,
            "after_sequence": after_sequence,
            "limit": limit,
            "next_after_sequence": max(
                [int(event["sequence"]) for event in page] or [after_sequence]
            ),
            "has_more": len(events) > limit,
            "events": page,
        }


def _workflow_payload(workflow_id: str = WORKFLOW_ID) -> dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "name": "Workflow smoke review",
        "description": "Exercise WorkflowRun public replay boundaries.",
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            {"id": "agent-review", "type": "agent", "label": "Review"},
            {"id": "artifact", "type": "artifact", "label": "Write report"},
        ],
        "edges": [
            {"source": "start", "target": "agent-review"},
            {"source": "agent-review", "target": "artifact"},
        ],
        "default_input_schema": {"type": "object"},
        "enabled": True,
        "created_at": "2026-06-29T00:00:00Z",
        "updated_at": "2026-06-29T00:00:01Z",
    }


def _workflow_run_events(run_id: str = WORKFLOW_RUN_ID) -> list[dict[str, Any]]:
    return [
        {
            "run_id": run_id,
            "sequence": 1,
            "event_type": "workflow.run.started",
            "detail": "Workflow smoke review",
            "payload": {
                "workflow_id": WORKFLOW_ID,
                "workflow_run_id": run_id,
                "objective": "Review launch evidence",
                "status": "running",
            },
        },
        {
            "run_id": run_id,
            "sequence": 2,
            "event_type": "workflow.node.started",
            "detail": "Review",
            "payload": {
                "workflow_id": WORKFLOW_ID,
                "workflow_run_id": run_id,
                "workflow_node_id": "agent-review",
                "workflow_node_label": "Review",
                "child_run_id": CHILD_RUN_ID,
                "child_run_kind": "agent_run",
                "child_run_status": "approval_required",
                "agent_id": "agent-reviewer",
            },
        },
        {
            "run_id": CHILD_RUN_ID,
            "sequence": 3,
            "event_type": "agent.tool.approval_required",
            "detail": "terminal.run",
            "payload": {
                "workflow_id": WORKFLOW_ID,
                "workflow_run_id": run_id,
                "workflow_node_id": "agent-review",
                "workflow_node_label": "Review",
                "run_id": CHILD_RUN_ID,
                "approval_id": APPROVAL_ID,
                "tool": "terminal.run",
                "input_preview": {"command": "printf workflow"},
            },
        },
        {
            "run_id": CHILD_RUN_ID,
            "sequence": 4,
            "event_type": "agent.artifact.created",
            "detail": ARTIFACT_PATH,
            "payload": {
                "workflow_id": WORKFLOW_ID,
                "workflow_run_id": run_id,
                "workflow_node_id": "artifact",
                "workflow_node_label": "Write report",
                "run_id": CHILD_RUN_ID,
                "artifact_id": "artifact-workflow-smoke",
                "kind": "markdown",
                "path": ARTIFACT_PATH,
            },
        },
    ]


def _workflow_run_payload(
    *,
    run_id: str = WORKFLOW_RUN_ID,
    workflow_id: str = WORKFLOW_ID,
    objective: str = "Review launch evidence",
    status: str = "approval_required",
    final_answer: str = "",
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "workflow_run_id": run_id,
        "workflow_id": workflow_id,
        "kind": "workflow_run",
        "runnable_id": workflow_id,
        "status": status,
        "title": "Workflow smoke review",
        "objective": objective,
        "user_goal": objective,
        "current_node_id": "agent-review",
        "current_node_label": "Review",
        "events": _workflow_run_events(run_id),
        "children": [
            {
                "run_id": CHILD_RUN_ID,
                "kind": "agent_run",
                "status": "approval_required",
                "workflow_run_id": run_id,
                "workflow_node_id": "agent-review",
                "workflow_node_label": "Review",
                "agent_id": "agent-reviewer",
            }
        ],
        "pending_approval": {
            "approval_id": APPROVAL_ID,
            "run_id": CHILD_RUN_ID,
            "workflow_run_id": run_id,
            "tool": "terminal.run",
            "input_preview": {"command": "printf workflow"},
        },
        "artifacts": [
            {
                "artifact_id": "artifact-workflow-smoke",
                "kind": "markdown",
                "path": ARTIFACT_PATH,
                "run_id": CHILD_RUN_ID,
                "source_run_id": CHILD_RUN_ID,
                "workflow_id": workflow_id,
                "workflow_run_id": run_id,
                "workflow_node_id": "artifact",
                "workflow_node_label": "Write report",
            }
        ],
        "final_answer": final_answer,
        "created_at": "2026-06-29T00:00:00Z",
        "updated_at": "2026-06-29T00:00:04Z",
    }


def _dump(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json")


def run_smoke() -> dict[str, Any]:
    port = _FakeWorkflowRunPort()
    service = AgentStudioService(port)
    workflows = service.list_workflows()
    workflow = service.get_workflow(WORKFLOW_ID)
    started = service.start_workflow_run(
        StartWorkflowRunRequest(
            workflow_id=WORKFLOW_ID,
            objective="Review launch evidence",
            client_run_id="client-workflow-smoke",
        )
    )
    listed_runs = service.list_run_timelines(5)
    fetched = service.get_run_timeline(WORKFLOW_RUN_ID)
    stream = list(service.get_run_event_stream(WORKFLOW_RUN_ID))
    page = service.get_run_event_page(WORKFLOW_RUN_ID, after_sequence=1, limit=2)

    workflow_payload = _dump(workflow)
    workflows_payload = [_dump(item) for item in workflows]
    started_payload = _dump(started)
    listed_payload = [_dump(item) for item in listed_runs]
    fetched_payload = _dump(fetched)
    stream_payload = [event.model_dump(mode="json") for event in stream]
    page_payload = page.model_dump(mode="json")
    call_names = [call["name"] for call in port.calls]
    child = started.children[0]
    checks = {
        "workflow_list_shape": workflows[0].workflow_id == WORKFLOW_ID
        and workflows[0].nodes[1]["id"] == "agent-review",
        "workflow_get_shape": workflow.workflow_id == WORKFLOW_ID
        and workflow.default_input_schema == {"type": "object"},
        "start_request_preserved": port.calls[2]["request"]["workflow_id"] == WORKFLOW_ID
        and port.calls[2]["request"]["objective"] == "Review launch evidence"
        and port.calls[2]["request"]["client_run_id"] == "client-workflow-smoke",
        "snapshot_shape": started.run_id == WORKFLOW_RUN_ID
        and started.workflow_run_id == WORKFLOW_RUN_ID
        and started.workflow_id == WORKFLOW_ID
        and started.status == "approval_required"
        and started.objective == "Review launch evidence",
        "current_node_context": started.current_node_id == "agent-review"
        and started.current_node_label == "Review",
        "child_context": child.run_id == CHILD_RUN_ID
        and child.workflow_run_id == WORKFLOW_RUN_ID
        and child.workflow_node_id == "agent-review"
        and child.agent_id == "agent-reviewer",
        "approval_context": started.pending_approval is not None
        and started.pending_approval.approval_id == APPROVAL_ID
        and started.pending_approval.workflow_run_id == WORKFLOW_RUN_ID,
        "artifact_context": any(
            artifact.path == ARTIFACT_PATH
            and artifact.workflow_run_id == WORKFLOW_RUN_ID
            and artifact.source_run_id == CHILD_RUN_ID
            for artifact in started.artifacts
        ),
        "event_stream_context": [event.event_type for event in stream[:2]]
        == ["workflow.run.started", "workflow.node.started"]
        and stream[0].payload["workflow_run_id"] == WORKFLOW_RUN_ID,
        "event_page_bounds": page.run_id == WORKFLOW_RUN_ID
        and page.after_sequence == 1
        and page.limit == 2
        and [event.event_type for event in page.events]
        == ["workflow.node.started", "agent.tool.approval_required"]
        and page.has_more is True,
        "listed_workflow_run": listed_runs[0].run_id == LISTED_WORKFLOW_RUN_ID
        and listed_runs[0].workflow_id == WORKFLOW_ID,
        "fetched_workflow_run": fetched.run_id == WORKFLOW_RUN_ID
        and fetched.workflow_id == WORKFLOW_ID,
        "port_call_order": call_names
        == [
            "list_workflows",
            "get_workflow",
            "start_workflow_run",
            "list_run_timelines",
            "get_run_timeline",
            "get_run_event_stream",
            "get_run_event_page",
        ],
    }
    return {
        "ok": all(checks.values()),
        "mode": "workflow_run_timeline_smoke",
        "workflow": workflow_payload,
        "workflows": workflows_payload,
        "started": started_payload,
        "listed": listed_payload,
        "fetched": fetched_payload,
        "event_stream": stream_payload,
        "event_page": page_payload,
        "calls": port.calls,
        "checks": checks,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional JSON evidence report path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = run_smoke()
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
        print(f"workflow run timeline smoke report: {args.report_json}", file=sys.stderr)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
