"""Tests for shared Chat/Studio run snapshot projection."""

from __future__ import annotations

from apps.shell.yachiyo_agent.run_snapshots import (
    RunSnapshotProjector,
    agent_task_snapshot_from_payload,
    run_timeline_snapshot_from_payload,
)
from apps.shell.yachiyo_agent.task_cards import (
    agent_task_snapshot_from_payload as legacy_task_snapshot_from_payload,
)
from apps.shell.yachiyo_agent.timelines import (
    run_timeline_snapshot_from_payload as legacy_timeline_snapshot_from_payload,
)


def _run_payload() -> dict:
    return {
        "task_id": "task-1",
        "run_id": "run-1",
        "session_id": "chat-1",
        "kind": "agent_run",
        "runnable_id": "agent-1",
        "user_goal": "Patch README",
        "status": "approval_required",
        "pending_approval": {
            "approval_id": "approval-1",
            "tool": "workspace.write_patch",
            "input_preview": {"path": "README.md"},
        },
        "timeline": [
            {
                "event": "agent.tool.call",
                "detail": "workspace.read",
                "input_preview": {"path": "README.md"},
                "result": {"ok": True},
            },
            {
                "event": "agent.tool.approval_required",
                "detail": "workspace.write_patch",
            },
        ],
        "artifacts": [
            {
                "kind": "markdown",
                "path": "reports/final.md",
                "bytes": 42,
            }
        ],
        "child_run_ids": ["child-1"],
        "run_group_id": "group-1",
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:00:01Z",
    }


def test_run_snapshot_projector_drives_chat_task_and_studio_timeline_shapes() -> None:
    projector = RunSnapshotProjector()
    payload = _run_payload()

    task = projector.task_snapshot_from_payload(payload)
    timeline = projector.timeline_snapshot_from_payload(payload)

    assert task.task_id == "task-1"
    assert task.status == "waiting_approval"
    assert task.needs_user_action is True
    assert task.pending_approvals[0].approval_id == "approval-1"
    assert task.pending_approvals[0].open_in_studio_url == "#/agents?run_id=run-1"
    assert task.recent_events[0].event_type == "agent.tool.call"
    assert task.artifacts[0].source_run_id == "run-1"
    assert task.open_in_studio_url == "#/agents?run_id=run-1"

    assert timeline.run_id == "run-1"
    assert timeline.agent_id == "agent-1"
    assert timeline.run_group_id == "group-1"
    assert timeline.pending_approval is not None
    assert timeline.pending_approval.approval_id == "approval-1"
    assert timeline.tool_calls[0].tool_name == "workspace.read"
    assert timeline.tool_calls[0].input_preview == {"path": "README.md"}
    assert timeline.tool_calls[0].output_preview == {"ok": True}
    assert timeline.artifacts[0].path == "reports/final.md"
    assert timeline.children[0].run_id == "child-1"


def test_legacy_task_and_timeline_functions_delegate_to_shared_projector() -> None:
    payload = _run_payload()

    assert legacy_task_snapshot_from_payload(payload) == agent_task_snapshot_from_payload(payload)
    assert legacy_timeline_snapshot_from_payload(payload) == run_timeline_snapshot_from_payload(payload)
