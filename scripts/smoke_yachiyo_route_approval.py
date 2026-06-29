#!/usr/bin/env python3
"""Smoke-test Yachiyo Chat and Studio approval route boundaries."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.bridge.routes import yachiyo
from apps.bridge.routes import yachiyo_chat_handlers
from apps.bridge.routes import yachiyo_studio_run_handlers
from apps.shell.yachiyo_agent import (
    AgentTaskSnapshot,
    ArtifactContentSnapshot,
    PublicRunEvent,
    RunEventPageSnapshot,
    RunTimelineSnapshot,
)

CHAT_TASK_ID = "task-route-approval"
CHAT_APPROVAL_ID = "approval-chat-route"
STUDIO_RUN_ID = "run-route-approval"
STUDIO_APPROVAL_ID = "approval-studio-route"


class _FakeChatRouteService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def approve(self, task_id: str, decision: Any) -> AgentTaskSnapshot:
        payload = decision.model_dump(mode="json", exclude_none=True)
        self.calls.append({"name": "approve", "task_id": task_id, "decision": payload})
        return AgentTaskSnapshot(
            task_id=task_id,
            title="Approved route task",
            status="completed",
            summary="Approved from route",
        )

    def reject(self, task_id: str, decision: Any) -> AgentTaskSnapshot:
        payload = decision.model_dump(mode="json", exclude_none=True)
        self.calls.append({"name": "reject", "task_id": task_id, "decision": payload})
        return AgentTaskSnapshot(
            task_id=task_id,
            title="Rejected route task",
            status="failed",
            summary="Rejected from route",
        )

    def get_task_event_page(
        self,
        task_id: str,
        after_sequence: int,
        limit: int,
    ) -> RunEventPageSnapshot:
        self.calls.append(
            {
                "name": "get_task_event_page",
                "task_id": task_id,
                "after_sequence": after_sequence,
                "limit": limit,
            }
        )
        return RunEventPageSnapshot(
            run_id="run-chat-route",
            after_sequence=after_sequence,
            limit=limit,
            next_after_sequence=after_sequence + 1,
            has_more=False,
            events=[
                PublicRunEvent(
                    run_id="run-chat-route",
                    sequence=after_sequence + 1,
                    event_type="agent.tool.approval_approved",
                    payload={"approval_id": CHAT_APPROVAL_ID},
                )
            ],
        )


class _FakeStudioRouteService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def approve_run_approval(self, run_id: str, decision: Any) -> RunTimelineSnapshot:
        payload = decision.model_dump(mode="json", exclude_none=True)
        self.calls.append(
            {"name": "approve_run_approval", "run_id": run_id, "decision": payload}
        )
        return RunTimelineSnapshot(run_id=run_id, status="completed", task_id=CHAT_TASK_ID)

    def reject_run_approval(self, run_id: str, decision: Any) -> RunTimelineSnapshot:
        payload = decision.model_dump(mode="json", exclude_none=True)
        self.calls.append(
            {"name": "reject_run_approval", "run_id": run_id, "decision": payload}
        )
        return RunTimelineSnapshot(run_id=run_id, status="failed", task_id=CHAT_TASK_ID)

    def get_run_event_page(
        self,
        run_id: str,
        after_sequence: int,
        limit: int,
    ) -> RunEventPageSnapshot:
        self.calls.append(
            {
                "name": "get_run_event_page",
                "run_id": run_id,
                "after_sequence": after_sequence,
                "limit": limit,
            }
        )
        return RunEventPageSnapshot(
            run_id=run_id,
            after_sequence=after_sequence,
            limit=limit,
            next_after_sequence=after_sequence + 1,
            has_more=False,
            events=[
                PublicRunEvent(
                    run_id=run_id,
                    sequence=after_sequence + 1,
                    event_type="agent.tool.completed",
                    payload={"approval_id": STUDIO_APPROVAL_ID},
                )
            ],
        )

    def read_run_artifact(self, run_id: str, artifact_path: str) -> ArtifactContentSnapshot:
        self.calls.append(
            {"name": "read_run_artifact", "run_id": run_id, "artifact_path": artifact_path}
        )
        return ArtifactContentSnapshot(
            run_id=run_id,
            path=artifact_path,
            content="# Route artifact",
            mime_type="text/markdown",
        )


async def _run_chat_route_smoke() -> dict[str, Any]:
    service = _FakeChatRouteService()
    original_agent_service = yachiyo_chat_handlers.agent_service
    yachiyo_chat_handlers.agent_service = lambda _request=None: service  # type: ignore[assignment]
    try:
        approved = await yachiyo.approve_task_approval(
            CHAT_TASK_ID,
            CHAT_APPROVAL_ID,
            yachiyo.TaskApprovalRequest(
                reason="Looks safe",
                metadata={"surface": "bubble"},
            ),
            None,
        )
        rejected = await yachiyo.reject_task_approval(
            CHAT_TASK_ID,
            CHAT_APPROVAL_ID,
            yachiyo.TaskApprovalRequest(
                reason="No",
                metadata={"surface": "live2d"},
            ),
            None,
        )
        events = await yachiyo.get_task_events(
            CHAT_TASK_ID,
            None,
            after_sequence=3,
            limit=1,
        )
    finally:
        yachiyo_chat_handlers.agent_service = original_agent_service  # type: ignore[assignment]

    approve_call = service.calls[0]
    reject_call = service.calls[1]
    event_call = service.calls[2]
    checks = {
        "approve_snapshot_shape": approved["task_id"] == CHAT_TASK_ID
        and approved["status"] == "completed",
        "reject_snapshot_shape": rejected["task_id"] == CHAT_TASK_ID
        and rejected["status"] == "failed",
        "approve_preserves_route_approval_id": approve_call["decision"]["metadata"][
            "approval_id"
        ]
        == CHAT_APPROVAL_ID,
        "approve_preserves_surface_metadata": approve_call["decision"]["metadata"]["surface"]
        == "bubble",
        "reject_sets_approved_false": reject_call["decision"]["approved"] is False,
        "reject_preserves_route_approval_id": reject_call["decision"]["metadata"][
            "approval_id"
        ]
        == CHAT_APPROVAL_ID,
        "event_page_uses_query_bounds": event_call["after_sequence"] == 3
        and event_call["limit"] == 1
        and events["events"][0]["event_type"] == "agent.tool.approval_approved",
    }
    return {
        "ok": all(checks.values()),
        "approved": approved,
        "rejected": rejected,
        "events": events,
        "calls": service.calls,
        "checks": checks,
    }


async def _run_studio_route_smoke() -> dict[str, Any]:
    service = _FakeStudioRouteService()
    original_studio_service = yachiyo_studio_run_handlers.studio_service
    yachiyo_studio_run_handlers.studio_service = lambda _request=None: service  # type: ignore[assignment]
    try:
        approved = await yachiyo.approve_studio_run_approval(
            STUDIO_RUN_ID,
            request=yachiyo.TaskApprovalRequest(
                approval_id=STUDIO_APPROVAL_ID,
                reason="Looks safe",
                metadata={"surface": "studio"},
            ),
            http_request=None,
        )
        rejected = await yachiyo.reject_studio_run_approval(
            STUDIO_RUN_ID,
            yachiyo.TaskApprovalRequest(
                approval_id=STUDIO_APPROVAL_ID,
                reason="No",
                metadata={"surface": "studio"},
            ),
            None,
        )
        events = await yachiyo.get_studio_run_events(
            STUDIO_RUN_ID,
            None,
            after_sequence=5,
            limit=2,
        )
        artifact = await yachiyo.get_studio_run_artifact(
            STUDIO_RUN_ID,
            "approval/route.md",
            None,
        )
    finally:
        yachiyo_studio_run_handlers.studio_service = original_studio_service  # type: ignore[assignment]

    approve_call = service.calls[0]
    reject_call = service.calls[1]
    event_call = service.calls[2]
    artifact_call = service.calls[3]
    checks = {
        "approve_snapshot_shape": approved["run_id"] == STUDIO_RUN_ID
        and approved["status"] == "completed",
        "reject_snapshot_shape": rejected["run_id"] == STUDIO_RUN_ID
        and rejected["status"] == "failed",
        "approve_preserves_approval_id": approve_call["decision"]["metadata"][
            "approval_id"
        ]
        == STUDIO_APPROVAL_ID,
        "approve_preserves_surface_metadata": approve_call["decision"]["metadata"][
            "surface"
        ]
        == "studio",
        "reject_sets_approved_false": reject_call["decision"]["approved"] is False,
        "event_page_uses_query_bounds": event_call["after_sequence"] == 5
        and event_call["limit"] == 2
        and events["events"][0]["event_type"] == "agent.tool.completed",
        "artifact_route_shape": artifact_call["artifact_path"] == "approval/route.md"
        and artifact["content"] == "# Route artifact",
    }
    return {
        "ok": all(checks.values()),
        "approved": approved,
        "rejected": rejected,
        "events": events,
        "artifact": artifact,
        "calls": service.calls,
        "checks": checks,
    }


async def _run_async_smoke() -> dict[str, Any]:
    chat = await _run_chat_route_smoke()
    studio = await _run_studio_route_smoke()
    return {
        "ok": chat["ok"] and studio["ok"],
        "mode": "yachiyo_route_approval_smoke",
        "chat": chat,
        "studio": studio,
    }


def run_smoke() -> dict[str, Any]:
    return asyncio.run(_run_async_smoke())


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
        print(
            f"Yachiyo route approval smoke report: {args.report_json}",
            file=sys.stderr,
        )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
