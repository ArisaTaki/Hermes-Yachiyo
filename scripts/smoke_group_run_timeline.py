#!/usr/bin/env python3
"""Smoke-test GroupRun public snapshots, replay events, and Studio service calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.yachiyo_agent import AgentStudioService, StartGroupRunRequest

GROUP_ID = "group-smoke"
GROUP_RUN_ID = "group-run-smoke"
LISTED_GROUP_RUN_ID = "group-run-listed"
CHILD_RUN_ID = "run-group-child-smoke"
APPROVAL_ID = "approval-group-smoke"
ARTIFACT_PATH = "groups/smoke-summary.md"


class _FakeGroupRunPort:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def start_group_run(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"name": "start_group_run", "request": request})
        return _group_run_payload(
            group_run_id=GROUP_RUN_ID,
            group_id=str(request.get("group_id") or GROUP_ID),
            objective=str(request.get("objective") or ""),
            status="approval_required",
        )

    def list_group_runs(self, limit: int = 50) -> dict[str, Any]:
        self.calls.append({"name": "list_group_runs", "limit": limit})
        return {
            "ok": True,
            "group_runs": [
                _group_run_payload(
                    group_run_id=LISTED_GROUP_RUN_ID,
                    status="completed",
                    final_answer="Listed group run completed.",
                )
            ],
        }

    def get_group_run(self, group_run_id: str) -> dict[str, Any]:
        self.calls.append({"name": "get_group_run", "group_run_id": group_run_id})
        return _group_run_payload(group_run_id=group_run_id, status="approval_required")

    def get_group_run_event_stream(self, group_run_id: str) -> dict[str, Any]:
        self.calls.append(
            {"name": "get_group_run_event_stream", "group_run_id": group_run_id}
        )
        return {"ok": True, "events": _group_run_events(group_run_id)}

    def get_group_run_event_page(
        self,
        group_run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "name": "get_group_run_event_page",
                "group_run_id": group_run_id,
                "after_sequence": after_sequence,
                "limit": limit,
            }
        )
        events = [
            event
            for event in _group_run_events(group_run_id)
            if int(event["sequence"]) > after_sequence
        ]
        page = events[:limit]
        return {
            "run_id": group_run_id,
            "after_sequence": after_sequence,
            "limit": limit,
            "next_after_sequence": max(
                [int(event["sequence"]) for event in page] or [after_sequence]
            ),
            "has_more": len(events) > limit,
            "events": page,
        }


def _group_run_events(group_run_id: str = GROUP_RUN_ID) -> list[dict[str, Any]]:
    return [
        {
            "run_id": group_run_id,
            "sequence": 1,
            "event_type": "group.run.started",
            "payload": {
                "group_id": GROUP_ID,
                "group_run_id": group_run_id,
                "objective": "Compare launch options",
            },
        },
        {
            "run_id": group_run_id,
            "sequence": 2,
            "event_type": "group.member.started",
            "payload": {
                "group_id": GROUP_ID,
                "group_run_id": group_run_id,
                "member_agent_id": "agent-planner",
                "run_id": CHILD_RUN_ID,
            },
        },
        {
            "run_id": CHILD_RUN_ID,
            "sequence": 3,
            "event_type": "agent.tool.approval_required",
            "payload": {
                "group_run_id": group_run_id,
                "run_id": CHILD_RUN_ID,
                "approval_id": APPROVAL_ID,
                "tool": "terminal.run",
                "input_preview": {"command": "printf group"},
            },
        },
        {
            "run_id": CHILD_RUN_ID,
            "sequence": 4,
            "event_type": "agent.artifact.created",
            "payload": {
                "group_id": GROUP_ID,
                "group_run_id": group_run_id,
                "run_id": CHILD_RUN_ID,
                "artifact_id": "artifact-group-smoke",
                "kind": "markdown",
                "path": ARTIFACT_PATH,
            },
        },
    ]


def _run_payload(group_run_id: str = GROUP_RUN_ID) -> dict[str, Any]:
    return {
        "run_id": CHILD_RUN_ID,
        "run_group_id": group_run_id,
        "group_run_id": group_run_id,
        "group_id": GROUP_ID,
        "kind": "agent_run",
        "runnable_id": "agent-planner",
        "status": "approval_required",
        "user_goal": "Compare launch options",
        "timeline": [
            {
                "event": "agent.tool.call",
                "detail": "workspace.read",
                "input_preview": {"path": "brief.md"},
            }
        ],
        "pending_approval": {
            "approval_id": APPROVAL_ID,
            "tool": "terminal.run",
            "input_preview": {
                "command": "printf group",
                "group_run_id": group_run_id,
            },
        },
        "artifacts": [
            {
                "artifact_id": "artifact-group-smoke",
                "kind": "markdown",
                "path": ARTIFACT_PATH,
            }
        ],
        "created_at": "2026-06-29T00:00:00Z",
        "updated_at": "2026-06-29T00:00:02Z",
    }


def _group_run_payload(
    *,
    group_run_id: str = GROUP_RUN_ID,
    group_id: str = GROUP_ID,
    objective: str = "Compare launch options",
    status: str = "approval_required",
    final_answer: str = "",
) -> dict[str, Any]:
    return {
        "group_run_id": group_run_id,
        "run_group_id": group_run_id,
        "group_id": group_id,
        "title": "Group launch review",
        "status": status,
        "objective": objective,
        "participants": [
            {
                "agent_id": "agent-planner",
                "name": "Planner",
                "role": "lead",
                "run_id": CHILD_RUN_ID,
            }
        ],
        "active_speaker_agent_id": "agent-planner",
        "events": _group_run_events(group_run_id),
        "runs": [_run_payload(group_run_id)],
        "child_run_ids": [CHILD_RUN_ID],
        "shared_artifacts": [
            {"artifact_id": "artifact-team", "kind": "markdown", "path": "team.md"}
        ],
        "pending_approvals": [
            {
                "approval_id": APPROVAL_ID,
                "tool": "terminal.run",
                "input_preview": {"command": "printf group"},
            }
        ],
        "final_answer": final_answer,
        "created_at": "2026-06-29T00:00:00Z",
        "updated_at": "2026-06-29T00:00:03Z",
    }


def _dump(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json")


def run_smoke() -> dict[str, Any]:
    port = _FakeGroupRunPort()
    service = AgentStudioService(port)
    started = service.start_group_run(
        StartGroupRunRequest(
            group_id=GROUP_ID,
            objective="Compare launch options",
            client_run_id="client-group-smoke",
        )
    )
    listed = service.list_group_runs(5)
    fetched = service.get_group_run(GROUP_RUN_ID)
    stream = list(service.get_group_run_event_stream(GROUP_RUN_ID))
    page = service.get_group_run_event_page(GROUP_RUN_ID, after_sequence=1, limit=2)

    started_payload = _dump(started)
    fetched_payload = _dump(fetched)
    listed_payload = [_dump(item) for item in listed]
    stream_payload = [event.model_dump(mode="json") for event in stream]
    page_payload = page.model_dump(mode="json")
    call_names = [call["name"] for call in port.calls]
    participant = started.participants[0]
    checks = {
        "start_request_preserved": port.calls[0]["request"]["group_id"] == GROUP_ID
        and port.calls[0]["request"]["objective"] == "Compare launch options"
        and port.calls[0]["request"]["client_run_id"] == "client-group-smoke",
        "snapshot_shape": started.group_run_id == GROUP_RUN_ID
        and started.run_group_id == GROUP_RUN_ID
        and started.group_id == GROUP_ID
        and started.status == "approval_required",
        "participant_rollup": participant.run_id == CHILD_RUN_ID
        and participant.run_status == "approval_required"
        and bool(participant.pending_approvals)
        and bool(participant.artifacts),
        "child_run_context": started.runs[0].run_group_id == GROUP_RUN_ID
        and started.runs[0].group_run_id == GROUP_RUN_ID,
        "approval_context": started.pending_approvals[0].approval_id == APPROVAL_ID
        and started.pending_approvals[0].group_run_id == GROUP_RUN_ID,
        "artifact_context": any(
            artifact.path == ARTIFACT_PATH
            and artifact.source_run_id == CHILD_RUN_ID
            and artifact.group_run_id == GROUP_RUN_ID
            for artifact in started.shared_artifacts
        ),
        "event_stream_context": [event.event_type for event in stream[:2]]
        == ["group.run.started", "group.member.started"]
        and stream[0].payload["group_run_id"] == GROUP_RUN_ID,
        "event_page_bounds": page.run_id == GROUP_RUN_ID
        and page.after_sequence == 1
        and page.limit == 2
        and [event.event_type for event in page.events]
        == ["group.member.started", "agent.tool.approval_required"]
        and page.has_more is True,
        "listed_group_run": listed[0].group_run_id == LISTED_GROUP_RUN_ID,
        "fetched_group_run": fetched.group_run_id == GROUP_RUN_ID
        and fetched.child_run_ids == [CHILD_RUN_ID],
        "port_call_order": call_names
        == [
            "start_group_run",
            "list_group_runs",
            "get_group_run",
            "get_group_run_event_stream",
            "get_group_run_event_page",
        ],
    }
    return {
        "ok": all(checks.values()),
        "mode": "group_run_timeline_smoke",
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
        print(f"group run timeline smoke report: {args.report_json}", file=sys.stderr)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
