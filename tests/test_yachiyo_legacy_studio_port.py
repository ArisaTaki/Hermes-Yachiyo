"""Legacy Agent Studio runtime port tests."""

from __future__ import annotations

from typing import Any

from apps.shell.yachiyo_agent.legacy_ports import LegacyStudioPort


def test_legacy_studio_group_run_records_group_run_started_event() -> None:
    runtime = _FakeGroupRuntime()

    group_run = LegacyStudioPort(runtime).start_group_run(
        {
            "group_id": "group-1",
            "objective": "Compare options",
            "client_run_id": "client-group-run-1",
        }
    )

    assert group_run["group_run_id"] == "group-run-1"
    assert group_run["child_run_ids"] == ["run-1", "run-2"]
    assert [event["event_type"] for event in group_run["events"]] == [
        "group.run.started",
        "group.run.plan",
        "group.member.started",
        "group.member.started",
    ]
    started = group_run["events"][0]
    assert started["run_id"] == "run-1"
    assert started["payload"]["group_run_id"] == "group-run-1"
    assert started["payload"]["group_id"] == "group-1"
    assert started["payload"]["objective"] == "Compare options"
    assert started["payload"]["participant_count"] == 2
    assert started["payload"]["client_run_id"] == "client-group-run-1"
    plan = group_run["events"][1]
    assert plan["payload"]["group_execution_mode"] == "parallel"
    assert plan["payload"]["group_execution_strategy"] == "fan_out"
    assert plan["payload"]["group_parallel"] is True
    assert plan["payload"]["group_member_order"] == ["agent-1", "agent-2"]


def test_legacy_studio_group_run_records_member_failed_and_cancelled_events() -> None:
    runtime = _FakeGroupRuntime(
        statuses={
            "agent-1": "failed",
            "agent-2": "cancelled",
        }
    )

    group_run = LegacyStudioPort(runtime).start_group_run(
        {
            "group_id": "group-1",
            "objective": "Compare options",
        }
    )

    assert [event["event_type"] for event in group_run["events"]] == [
        "group.run.started",
        "group.run.plan",
        "group.member.started",
        "group.member.failed",
        "group.member.started",
        "group.member.cancelled",
    ]
    assert group_run["events"][3]["payload"]["status"] == "failed"
    assert group_run["events"][5]["payload"]["status"] == "cancelled"


def test_legacy_studio_port_forwards_run_event_page_cursor_to_runtime() -> None:
    runtime = _FakeGroupRuntime()
    port = LegacyStudioPort(runtime)

    page = port.get_run_event_page("run-1", after_sequence=4, limit=2)

    assert page["run_id"] == "run-1"
    assert page["after_sequence"] == 4
    assert page["limit"] == 2
    assert runtime.last_event_page_request == {
        "run_id": "run-1",
        "after_sequence": 4,
        "limit": 2,
    }


def test_legacy_studio_port_accepts_reject_decision_payload() -> None:
    runtime = _FakeGroupRuntime()
    port = LegacyStudioPort(runtime)

    rejected = port.reject_run_approval(
        "run-1",
        {
            "approved": False,
            "reason": "No",
            "metadata": {"approval_id": "approval-1"},
        },
    )

    assert rejected["status"] == "failed"
    assert runtime.last_reject_request == {"run_id": "run-1", "reason": "No"}


def test_legacy_studio_port_accepts_approve_decision_payload() -> None:
    runtime = _FakeGroupRuntime()
    port = LegacyStudioPort(runtime)

    approved = port.approve_run_approval(
        "run-1",
        {
            "approved": True,
            "reason": "Looks safe",
            "metadata": {"approval_id": "approval-1"},
        },
    )

    assert approved["status"] == "completed"
    assert runtime.last_approve_request == {"run_id": "run-1"}


class _FakeGroupRuntime:
    def __init__(self, statuses: dict[str, str] | None = None) -> None:
        self.child_run_ids: list[str] = []
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.last_approve_request: dict[str, Any] | None = None
        self.last_event_page_request: dict[str, Any] | None = None
        self.last_reject_request: dict[str, Any] | None = None
        self.runs: dict[str, dict[str, Any]] = {}
        self.statuses = statuses or {}
        self.group = {
            "group_id": "group-1",
            "name": "Review team",
            "mode": "parallel",
            "memory_scope": "shared",
            "members": [
                {"agent_id": "agent-1", "name": "Planner", "role": "planner"},
                {"agent_id": "agent-2", "name": "Reviewer", "role": "reviewer"},
            ],
        }

    def get_agent_group(self, group_id: str) -> dict[str, Any]:
        if group_id != "group-1":
            raise KeyError(group_id)
        return dict(self.group)

    def create_run_for_runnable_async(
        self,
        *,
        runnable_id: str,
        user_goal: str,
        run_group_id: str = "",
        on_complete: Any | None = None,
    ) -> dict[str, Any]:
        del on_complete
        clean_run_group_id = run_group_id or "group-run-1"
        run_id = f"run-{len(self.runs) + 1}"
        status = self.statuses.get(runnable_id, "processing")
        run = {
            "artifacts": [],
            "pending_approval": {},
            "run_group_id": clean_run_group_id,
            "run_id": run_id,
            "runnable_id": runnable_id,
            "runnable_name": runnable_id,
            "status": status,
            "user_goal": user_goal,
        }
        self.runs[run_id] = run
        self.child_run_ids.append(run_id)
        return dict(run)

    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event = {
            "event_type": event_type,
            "payload": dict(payload),
            "run_id": run_id,
        }
        self.events.setdefault(run_id, []).append(event)
        return event

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        return {
            "child_run_ids": list(self.child_run_ids),
            "created_at": "2026-06-16T00:00:00Z",
            "run_group_id": run_group_id,
            "status": "running",
            "summary": "",
            "title": "Review team",
            "updated_at": "2026-06-16T00:00:00Z",
        }

    def list_run_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        self.last_event_page_request = {
            "run_id": run_id,
            "after_sequence": after_sequence,
            "limit": limit,
        }
        return {
            "run_id": run_id,
            "after_sequence": after_sequence,
            "limit": limit,
            "events": list(self.events.get(run_id, [])),
        }

    def reject_run_approval(self, run_id: str, reason: str = "") -> dict[str, Any]:
        self.last_reject_request = {"run_id": run_id, "reason": reason}
        return {
            "run_id": run_id,
            "status": "failed",
            "user_goal": "Rejected",
        }

    def approve_run_approval(self, run_id: str) -> dict[str, Any]:
        self.last_approve_request = {"run_id": run_id}
        return {
            "run_id": run_id,
            "status": "completed",
            "user_goal": "Approved",
        }
