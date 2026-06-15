"""Tests for shared Chat/Studio run snapshot projection."""

from __future__ import annotations

from apps.shell.yachiyo_agent.run_snapshots import (
    RunSnapshotProjector,
    agent_task_snapshot_from_payload,
    run_timeline_snapshot_from_payload,
)
from apps.shell.yachiyo_agent.groups import group_run_snapshot_from_payload
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


def test_run_timeline_projects_tool_lifecycle_events_as_tool_call_snapshots() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-tools",
            "status": "running",
            "events": [
                {
                    "event_type": "tool.requested",
                    "payload": {
                        "tool": "workspace.read",
                        "input_preview": {"path": "README.md"},
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                },
                {
                    "event_type": "tool.started",
                    "payload": {
                        "tool": "workspace.read",
                        "input_preview": {"path": "README.md"},
                    },
                },
                {
                    "event_type": "tool.approval_required",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "output_preview": {"approval_required": True},
                    },
                },
                {
                    "event_type": "tool.completed",
                    "payload": {
                        "tool": "workspace.read",
                        "input_preview": {"path": "README.md"},
                        "output_preview": {"ok": True},
                    },
                },
                {
                    "event_type": "tool.failed",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "error": "exit 1",
                    },
                },
                {
                    "event": "agent.tool.denied",
                    "detail": "workspace.write",
                    "input_preview": {"path": "README.md"},
                },
                {"event_type": "model.output.completed", "payload": {"content": "done"}},
            ],
        }
    )

    assert [call.tool_name for call in timeline.tool_calls] == [
        "workspace.read",
        "workspace.read",
        "terminal.run",
        "workspace.read",
        "terminal.run",
        "workspace.write",
    ]
    assert [call.status for call in timeline.tool_calls] == [
        "requested",
        "running",
        "waiting_approval",
        "completed",
        "failed",
        "denied",
    ]
    assert timeline.tool_calls[0].input_preview == {"path": "README.md"}
    assert timeline.tool_calls[2].output_preview == {"approval_required": True}
    assert timeline.tool_calls[4].output_preview == {"error": "exit 1"}
    assert timeline.tool_calls[5].input_preview == {"path": "README.md"}
    assert all(call.run_id == "run-tools" for call in timeline.tool_calls)


def test_run_timeline_projects_legacy_agent_tool_lifecycle_events() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-legacy-tools",
            "status": "running",
            "timeline": [
                {"event": "agent.tool.completed", "detail": "workspace.read"},
                {"event": "agent.tool.failed", "detail": "terminal.run", "error": "exit 1"},
                {"event": "agent.tool.skipped", "detail": "workspace.write"},
                {"event": "agent.tool.approval_approved", "detail": "terminal.run"},
                {"event": "agent.tool.approval_rejected", "detail": "workspace.write"},
                {"event": "agent.tool.denied", "detail": "workspace.delete"},
            ],
        }
    )

    assert [call.tool_name for call in timeline.tool_calls] == [
        "workspace.read",
        "terminal.run",
        "workspace.write",
        "terminal.run",
        "workspace.write",
        "workspace.delete",
    ]
    assert [call.status for call in timeline.tool_calls] == [
        "completed",
        "failed",
        "skipped",
        "approved",
        "denied",
        "denied",
    ]
    assert timeline.tool_calls[1].output_preview == {"error": "exit 1"}
    assert all(call.run_id == "run-legacy-tools" for call in timeline.tool_calls)


def test_group_run_snapshot_reuses_shared_run_projection_for_children_artifacts_and_approvals() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-1",
            "group_id": "group-1",
            "title": "Team review",
            "status": "running",
            "objective": "Compare options",
            "runs": [_run_payload()],
            "shared_artifacts": [{"kind": "markdown", "path": "team.md"}],
            "pending_approvals": [{"approval_id": "approval-group", "tool": "terminal.run"}],
        }
    )

    assert group_run.group_run_id == "group-run-1"
    assert group_run.runs[0].run_id == "run-1"
    assert group_run.runs[0].tool_calls[0].tool_name == "workspace.read"
    assert group_run.runs[0].pending_approval is not None
    assert group_run.shared_artifacts[0].source_run_id == "group-run-1"
    assert group_run.shared_artifacts[0].path == "team.md"
    assert group_run.pending_approvals[0].run_id == "group-run-1"
    assert group_run.pending_approvals[0].open_in_studio_url == "#/agents?run_id=group-run-1"
