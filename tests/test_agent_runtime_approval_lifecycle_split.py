"""Tests for approval lifecycle coordinator split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.approval_lifecycle import (
    ApprovalCoordinator,
    ApprovalPauseProjectionCoordinator,
)
from apps.shell.agent.runtime.approval_snapshots import ApprovalSnapshotBuilder
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_approval_coordinator_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.ApprovalCoordinator is ApprovalCoordinator
    assert (
        agent_runtime.ApprovalPauseProjectionCoordinator
        is ApprovalPauseProjectionCoordinator
    )


def test_approval_pause_projection_projects_public_and_private_approval_state() -> None:
    timeline: list[dict[str, object]] = []
    events: list[tuple[str, str, dict[str, object]]] = []
    updates: list[tuple[str, dict[str, object]]] = []

    def timeline_factory(event: str, detail: str = "", **extra: object) -> dict[str, object]:
        return {"event": event, "detail": detail, **extra}

    def append_run_event(run_id: str, event_type: str, payload: dict[str, object]) -> None:
        events.append((run_id, event_type, payload))

    def update_run(run_id: str, **fields: object) -> dict[str, object]:
        updates.append((run_id, fields))
        return {"run_id": run_id, **fields}

    pending = {
        "approval_id": "approval-1",
        "tool": "terminal.run",
        "input_preview": {
            "command": "printf ok",
            "API_KEY": "sk-pause-secret123456",
        },
        "requested_at": "2026-06-15T00:00:00+00:00",
        "messages": [{"role": "user", "content": "private"}],
    }
    artifacts = [{"kind": "context", "path": "agent-context.md"}]
    coordinator = ApprovalPauseProjectionCoordinator(
        timeline_factory=timeline_factory,
        append_run_event=append_run_event,
        update_run=update_run,
        get_run=lambda _run_id: {
            "run_id": "run-1",
            "status": "running",
            "pending_approval": {},
            "updated_at": "2026-07-11T10:00:00+00:00",
        },
        snapshots=ApprovalSnapshotBuilder(),
    )

    projected = coordinator.project_tool_required(
        "run-1",
        pending_approval=pending,
        timeline=timeline,
        artifacts=artifacts,
    )

    public_pending = timeline[0]["pending_approval"]
    assert projected["status"] == "approval_required"
    assert projected["result"] == "等待审批：terminal.run"
    assert projected["pending_approval"]["messages"] == pending["messages"]
    assert projected["artifacts"] is artifacts
    assert timeline[0]["event"] == "agent.tool.approval_required"
    assert events == [("run-1", "agent.tool.approval_required", public_pending)]
    assert "messages" not in public_pending
    assert "sk-pause-secret123456" not in str(public_pending)
    assert updates[0][1]["pending_approval"]["messages"] == pending["messages"]


def test_approval_pause_projects_planner_trace_as_internal_private_audit() -> None:
    timeline: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        *,
        visibility: str = "user",
        sensitivity: str = "public",
    ) -> None:
        events.append(
            {
                "run_id": run_id,
                "event_type": event_type,
                "payload": payload,
                "visibility": visibility,
                "sensitivity": sensitivity,
            }
        )

    planner_trace = {
        "plan_id": "plan-private",
        "step_id": "send-message",
        "depends_on": ["focus-chat"],
        "desktop_loop": {"verification_target_step_ids": ["verify-message"]},
        "action_target": {"recipient": "private-recipient"},
        "observation_evidence": {"window": "private-window"},
    }
    contaminated_input = {"action": "send", **planner_trace}
    pending = {
        "approval_id": "approval-traced",
        "tool": "desktop.submit_foreground",
        "input": contaminated_input,
        "input_preview": contaminated_input,
        "tool_request": {
            "tool": "desktop.submit_foreground",
            "input": contaminated_input,
            **planner_trace,
        },
        **planner_trace,
    }
    coordinator = ApprovalPauseProjectionCoordinator(
        timeline_factory=lambda event, detail="", **extra: {
            "event": event,
            "detail": detail,
            **extra,
        },
        append_run_event=append_run_event,
        update_run=lambda run_id, **fields: {"run_id": run_id, **fields},
        get_run=lambda _run_id: {
            "run_id": "run-traced",
            "status": "running",
            "pending_approval": {},
            "updated_at": "2026-07-13T00:00:00+00:00",
        },
    )

    projected = coordinator.project_tool_required(
        "run-traced",
        pending_approval=pending,
        timeline=timeline,
        artifacts=[],
    )

    assert projected["pending_approval"]["tool_request"]["plan_id"] == "plan-private"
    assert events[0]["event_type"] == "agent.tool.approval_required"
    assert events[0]["visibility"] == "user"
    assert events[0]["payload"]["input_preview"] == {"action": "send"}
    assert "plan-private" not in str(events[0]["payload"])
    assert events[1]["event_type"] == "agent.tool.approval_trace"
    assert events[1]["visibility"] == "internal"
    assert events[1]["sensitivity"] == "private"
    assert events[1]["payload"]["planner_trace"]["plan_id"] == "plan-private"
    assert events[1]["payload"]["planner_trace"]["desktop_loop"] == {
        "verification_target_step_ids": ["verify-message"]
    }
    assert events[1]["payload"]["planner_trace"]["action_target"] == {
        "recipient": "private-recipient"
    }
    assert events[1]["payload"]["planner_trace"]["observation_evidence"] == {
        "window": "private-window"
    }
    assert events[1]["payload"]["non_executable_input"]["depends_on"] == [
        "focus-chat"
    ]


def test_approval_pause_projection_does_not_reuse_id_for_repeated_generation() -> None:
    timeline: list[dict[str, object]] = []
    updates: list[dict[str, object]] = []
    coordinator = ApprovalPauseProjectionCoordinator(
        timeline_factory=lambda event, detail="", **extra: {
            "event": event,
            "detail": detail,
            **extra,
        },
        append_run_event=lambda *_args, **_kwargs: {},
        update_run=lambda _run_id, **fields: updates.append(fields) or fields,
        get_run=lambda _run_id: {
            "run_id": "run-1",
            "status": "running",
            "pending_approval": {},
            "updated_at": "2026-07-11T10:00:00+00:00",
        },
        snapshots=ApprovalSnapshotBuilder(),
        approval_generation_factory=lambda: "generation-2",
    )
    pending = {
        "approval_id": "approval-deterministic",
        "tool": "desktop.safe_click",
        "input_preview": {"x": 10, "y": 20},
    }

    coordinator.project_tool_required(
        "run-1",
        pending_approval=pending,
        timeline=timeline,
        artifacts=[],
    )
    coordinator.project_tool_required(
        "run-1",
        pending_approval=pending,
        timeline=timeline,
        artifacts=[],
    )

    first_id = str(updates[0]["pending_approval"]["approval_id"])
    second_id = str(updates[1]["pending_approval"]["approval_id"])
    assert first_id == "approval-deterministic"
    assert second_id == "approval-deterministic-generation-2"
    assert second_id != first_id


def test_agent_runtime_service_uses_approval_pause_projection(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.approval_pause, ApprovalPauseProjectionCoordinator)
    finally:
        service.close()


def test_terminal_main_chat_run_cannot_be_resurrected_by_late_approval_pause(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        run = service.start_main_chat_run(
            task_id="task-terminal-winner",
            session_id="session-terminal-winner",
            user_goal="Open Notes",
        )
        pause = service.main_chat_model_loop._approval_pause
        terminal = service.complete_main_chat_run(run["run_id"], "Notes is open")
        projected = pause.project_tool_required(
            run["run_id"],
            pending_approval={
                "approval_id": "approval-too-late",
                "tool": "desktop.open_app",
                "input_preview": {"app": "Notes"},
            },
            timeline=list(run.get("timeline") or []),
            artifacts=[],
        )

        winner = service.get_run(run["run_id"])
        approval_events = [
            event
            for event in service.list_run_events(run["run_id"])["events"]
            if event["event_type"] == "agent.tool.approval_required"
        ]
        assert terminal["status"] == "completed"
        assert projected["status"] == "completed"
        assert winner["status"] == "completed"
        assert winner["pending_approval"] == {}
        assert approval_events == []
        approval_rows = service._conn.execute(
            "SELECT approval_id FROM run_approvals WHERE run_id=?",
            (run["run_id"],),
        ).fetchall()
        assert approval_rows == []
    finally:
        service.close()
