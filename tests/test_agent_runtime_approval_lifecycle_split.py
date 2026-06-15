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
