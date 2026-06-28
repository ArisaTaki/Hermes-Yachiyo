#!/usr/bin/env python3
"""Smoke-test approval resume projection across Chat and Agent Studio timelines."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.yachiyo_agent import (
    AgentStudioService,
    ApprovalDecision,
    RunEventPageSnapshot,
    RunTimelineSnapshot,
    StartChatTaskRequest,
    YachiyoAgentService,
)

TASK_ID = "task-approval-smoke"
RUN_ID = "run-approval-smoke"
APPROVAL_ID = "approval-ui-click"
TOOL_CALL_ID = "tool-call-ui-click"
TOOL_NAME = "app.focus_and_click_ui_element"


class _FakeApprovalResumePort:
    def __init__(self) -> None:
        self.approved = False
        self.calls: list[tuple[str, Any]] = []

    def start_chat_task(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_chat_task", request))
        self.approved = False
        return self._run_payload()

    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_timeline", task_id))
        return self._run_payload(task_id=task_id)

    def get_task_event_page(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "get_task_event_page",
                {"task_id": task_id, "after_sequence": after_sequence, "limit": limit},
            )
        )
        return self._event_page(after_sequence=after_sequence, limit=limit)

    def approve(self, task_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("approve", {"task_id": task_id, "decision": decision}))
        self.approved = True
        return self._run_payload(task_id=task_id)

    def get_run_timeline(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run_timeline", run_id))
        return self._run_payload(run_id=run_id)

    def get_run_event_page(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "get_run_event_page",
                {"run_id": run_id, "after_sequence": after_sequence, "limit": limit},
            )
        )
        return self._event_page(after_sequence=after_sequence, limit=limit)

    def approve_run_approval(
        self,
        run_id: str,
        decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("approve_run_approval", {"run_id": run_id, "decision": decision}))
        self.approved = True
        return self._run_payload(run_id=run_id)

    def _run_payload(
        self,
        *,
        task_id: str = TASK_ID,
        run_id: str = RUN_ID,
    ) -> dict[str, Any]:
        completed = self.approved
        payload = {
            "task_id": task_id,
            "run_id": run_id,
            "session_id": "chat-approval-smoke",
            "title": "Click a foreground UI element",
            "user_goal": "在 Notion 点击 New Page",
            "status": "completed" if completed else "approval_required",
            "summary": "Clicked New Page after approval." if completed else "Waiting for approval.",
            "current_step": "" if completed else "Waiting for approval",
            "timeline": _events(completed=completed, run_id=run_id),
            "created_at": "2026-06-29T00:00:00Z",
            "updated_at": "2026-06-29T00:00:05Z" if completed else "2026-06-29T00:00:02Z",
        }
        if not completed:
            payload["pending_approval"] = _pending_approval(run_id=run_id)
        else:
            payload["artifacts"] = [
                {
                    "artifact_id": "artifact-approval-log",
                    "kind": "markdown",
                    "path": "approval/resume-log.md",
                    "preview_text": "Approved UI click and completed the run.",
                }
            ]
        return payload

    def _event_page(self, *, after_sequence: int, limit: int) -> dict[str, Any]:
        events = _events(completed=self.approved, run_id=RUN_ID)
        filtered = [
            event
            for event in events
            if int(event.get("sequence") or 0) > int(after_sequence or 0)
        ]
        page = filtered[: max(1, int(limit or 200))]
        next_after_sequence = max(
            [int(event.get("sequence") or 0) for event in page] or [int(after_sequence or 0)]
        )
        return {
            "run_id": RUN_ID,
            "after_sequence": after_sequence,
            "limit": limit,
            "next_after_sequence": next_after_sequence,
            "has_more": len(filtered) > len(page),
            "events": page,
        }


def _pending_approval(*, run_id: str = RUN_ID) -> dict[str, Any]:
    return {
        "approval_id": APPROVAL_ID,
        "run_id": run_id,
        "tool": TOOL_NAME,
        "title": "Approve UI click",
        "risk_level": "medium",
        "policy_reason": "medium_risk_desktop_action",
        "input_preview": {
            "app_name": "Notion",
            "target": "New Page",
            "tool_call_id": TOOL_CALL_ID,
        },
        "requested_at": "2026-06-29T00:00:02Z",
    }


def _events(*, completed: bool, run_id: str) -> list[dict[str, Any]]:
    events = [
        {
            "event_id": "evt-started",
            "run_id": run_id,
            "sequence": 1,
            "event_type": "agent.started",
            "title": "Started",
            "payload": {"status": "running"},
            "created_at": "2026-06-29T00:00:00Z",
        },
        {
            "event_id": "evt-tool-call",
            "run_id": run_id,
            "sequence": 2,
            "event_type": "agent.tool.call",
            "detail": TOOL_NAME,
            "payload": {
                "tool_call_id": TOOL_CALL_ID,
                "tool": TOOL_NAME,
                "status": "waiting_approval",
                "approval_id": APPROVAL_ID,
                "risk_level": "medium",
                "input_preview": {"app_name": "Notion", "target": "New Page"},
            },
            "created_at": "2026-06-29T00:00:01Z",
        },
        {
            "event_id": "evt-approval-required",
            "run_id": run_id,
            "sequence": 3,
            "event_type": "agent.tool.approval_required",
            "detail": TOOL_NAME,
            "payload": {
                "tool_call_id": TOOL_CALL_ID,
                "tool": TOOL_NAME,
                "approval_id": APPROVAL_ID,
                "risk_level": "medium",
                "policy_reason": "medium_risk_desktop_action",
                "pending_approval": _pending_approval(run_id=run_id),
            },
            "created_at": "2026-06-29T00:00:02Z",
        },
    ]
    if completed:
        events.extend(
            [
                {
                    "event_id": "evt-approval-approved",
                    "run_id": run_id,
                    "sequence": 4,
                    "event_type": "agent.tool.approval_approved",
                    "detail": TOOL_NAME,
                    "payload": {
                        "tool_call_id": TOOL_CALL_ID,
                        "tool": TOOL_NAME,
                        "approval_id": APPROVAL_ID,
                        "reason": "Looks safe",
                    },
                    "created_at": "2026-06-29T00:00:03Z",
                },
                {
                    "event_id": "evt-tool-completed",
                    "run_id": run_id,
                    "sequence": 5,
                    "event_type": "agent.tool.completed",
                    "detail": TOOL_NAME,
                    "payload": {
                        "tool_call_id": TOOL_CALL_ID,
                        "tool": TOOL_NAME,
                        "approval_id": APPROVAL_ID,
                        "risk_level": "medium",
                        "input_preview": {"app_name": "Notion", "target": "New Page"},
                        "output_preview": {
                            "ok": True,
                            "summary": "Clicked New Page in Notion.",
                        },
                    },
                    "created_at": "2026-06-29T00:00:04Z",
                },
                {
                    "event_id": "evt-completed",
                    "run_id": run_id,
                    "sequence": 6,
                    "event_type": "agent.completed",
                    "title": "Completed",
                    "payload": {"status": "completed"},
                    "created_at": "2026-06-29T00:00:05Z",
                },
            ]
        )
    return events


def _event_types(events: Iterable[Any]) -> list[str]:
    return [str(getattr(event, "event_type", "") or "") for event in events]


def _timeline_summary(timeline: RunTimelineSnapshot) -> dict[str, Any]:
    return {
        "run_id": timeline.run_id,
        "task_id": timeline.task_id,
        "status": timeline.status,
        "event_types": _event_types(timeline.events),
        "pending_approval": _approval_summary(timeline.pending_approval),
        "approvals": [_approval_summary(approval) for approval in timeline.approvals],
        "tool_calls": [
            {
                "tool_call_id": call.tool_call_id,
                "tool": call.tool_name,
                "status": call.status,
                "risk_level": call.risk_level,
                "approval_id": call.approval_id,
                "output_preview": call.output_preview,
            }
            for call in timeline.tool_calls
        ],
        "artifacts": [
            {"path": artifact.path, "kind": artifact.kind}
            for artifact in timeline.artifacts
        ],
    }


def _approval_summary(approval: Any) -> dict[str, Any] | None:
    if approval is None:
        return None
    return {
        "approval_id": approval.approval_id,
        "status": approval.status,
        "tool": approval.tool_name,
        "risk_level": approval.risk_level,
        "policy_reason": approval.policy_reason,
        "input_preview": approval.input_preview,
    }


def _event_page_summary(page: RunEventPageSnapshot) -> dict[str, Any]:
    return {
        "run_id": page.run_id,
        "after_sequence": page.after_sequence,
        "next_after_sequence": page.next_after_sequence,
        "has_more": page.has_more,
        "event_types": _event_types(page.events),
    }


def _call_summary(call: tuple[str, Any]) -> dict[str, Any]:
    name, payload = call
    if isinstance(payload, dict):
        summary: dict[str, Any] = {"name": name}
        if payload.get("prompt"):
            summary["prompt"] = payload.get("prompt")
        if payload.get("conversation_id"):
            summary["conversation_id"] = payload.get("conversation_id")
        if payload.get("task_id"):
            summary["task_id"] = payload.get("task_id")
        if payload.get("run_id"):
            summary["run_id"] = payload.get("run_id")
        decision = payload.get("decision")
        if isinstance(decision, dict):
            summary["decision"] = decision
        for key in ("after_sequence", "limit"):
            if key in payload:
                summary[key] = payload[key]
        return summary
    return {"name": name, "value": payload}


def _chat_evidence() -> dict[str, Any]:
    port = _FakeApprovalResumePort()
    service = YachiyoAgentService(port)
    started = service.start_chat_task(
        StartChatTaskRequest(
            prompt="在 Notion 点击 New Page",
            conversation_id="chat-approval-smoke",
        )
    )
    before = service.get_task_timeline(TASK_ID)
    before_page = service.get_task_event_page(TASK_ID, after_sequence=0, limit=10)
    approved = service.approve(
        TASK_ID,
        ApprovalDecision(
            approved=True,
            reason="Looks safe",
            metadata={"approval_id": APPROVAL_ID},
        ),
    )
    after = service.get_task_timeline(TASK_ID)
    after_page = service.get_task_event_page(TASK_ID, after_sequence=3, limit=10)
    after_call = after.tool_calls[0] if after.tool_calls else None
    checks = {
        "started_waits_for_approval": started.status == "waiting_approval",
        "started_needs_user_action": started.needs_user_action is True,
        "started_has_pending_approval": bool(started.pending_approvals)
        and started.pending_approvals[0].approval_id == APPROVAL_ID,
        "before_timeline_pending": before.pending_approval is not None
        and before.pending_approval.status == "pending",
        "before_page_has_required_event": "agent.tool.approval_required"
        in _event_types(before_page.events),
        "approve_returns_completed_task": approved.status == "completed"
        and not approved.pending_approvals,
        "after_timeline_completed": after.status == "completed",
        "after_timeline_no_pending": after.pending_approval is None,
        "after_has_approved_resolution": any(
            approval.approval_id == APPROVAL_ID and approval.status == "approved"
            for approval in after.approvals
        ),
        "after_tool_call_completed": after_call is not None
        and after_call.status == "completed"
        and after_call.approval_id == APPROVAL_ID,
        "after_page_replays_resume_events": _event_types(after_page.events)
        == [
            "agent.tool.approval_approved",
            "agent.tool.completed",
            "agent.completed",
        ],
        "approval_payload_preserved": port.calls[3]
        == (
            "approve",
            {
                "task_id": TASK_ID,
                "decision": {
                    "approved": True,
                    "reason": "Looks safe",
                    "metadata": {"approval_id": APPROVAL_ID},
                },
            },
        ),
    }
    return {
        "ok": all(checks.values()),
        "started": {
            "task_id": started.task_id,
            "status": started.status,
            "needs_user_action": started.needs_user_action,
            "pending_approvals": [
                _approval_summary(approval) for approval in started.pending_approvals
            ],
        },
        "before_timeline": _timeline_summary(before),
        "before_event_page": _event_page_summary(before_page),
        "approved_task": {
            "task_id": approved.task_id,
            "status": approved.status,
            "needs_user_action": approved.needs_user_action,
            "pending_approvals": [
                _approval_summary(approval) for approval in approved.pending_approvals
            ],
        },
        "after_timeline": _timeline_summary(after),
        "after_event_page": _event_page_summary(after_page),
        "calls": [_call_summary(call) for call in port.calls],
        "checks": checks,
    }


def _studio_evidence() -> dict[str, Any]:
    port = _FakeApprovalResumePort()
    service = AgentStudioService(port)
    before = service.get_run_timeline(RUN_ID)
    before_page = service.get_run_event_page(RUN_ID, after_sequence=0, limit=10)
    approved = service.approve_run_approval(
        RUN_ID,
        ApprovalDecision(
            approved=True,
            reason="Looks safe",
            metadata={"approval_id": APPROVAL_ID},
        ),
    )
    after_page = service.get_run_event_page(RUN_ID, after_sequence=3, limit=10)
    after_call = approved.tool_calls[0] if approved.tool_calls else None
    checks = {
        "before_timeline_pending": before.status == "approval_required"
        and before.pending_approval is not None
        and before.pending_approval.approval_id == APPROVAL_ID,
        "before_page_has_required_event": "agent.tool.approval_required"
        in _event_types(before_page.events),
        "approved_timeline_completed": approved.status == "completed",
        "approved_timeline_no_pending": approved.pending_approval is None,
        "approved_resolution_visible": any(
            approval.approval_id == APPROVAL_ID and approval.status == "approved"
            for approval in approved.approvals
        ),
        "approved_tool_completed": after_call is not None
        and after_call.status == "completed"
        and after_call.approval_id == APPROVAL_ID,
        "after_page_replays_resume_events": _event_types(after_page.events)
        == [
            "agent.tool.approval_approved",
            "agent.tool.completed",
            "agent.completed",
        ],
        "approval_payload_preserved": port.calls[2]
        == (
            "approve_run_approval",
            {
                "run_id": RUN_ID,
                "decision": {
                    "approved": True,
                    "reason": "Looks safe",
                    "metadata": {"approval_id": APPROVAL_ID},
                },
            },
        ),
    }
    return {
        "ok": all(checks.values()),
        "before_timeline": _timeline_summary(before),
        "before_event_page": _event_page_summary(before_page),
        "approved_timeline": _timeline_summary(approved),
        "after_event_page": _event_page_summary(after_page),
        "calls": [_call_summary(call) for call in port.calls],
        "checks": checks,
    }


def run_smoke() -> dict[str, Any]:
    chat = _chat_evidence()
    studio = _studio_evidence()
    return {
        "ok": chat["ok"] and studio["ok"],
        "mode": "approval_resume_timeline_smoke",
        "chat": chat,
        "studio": studio,
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
