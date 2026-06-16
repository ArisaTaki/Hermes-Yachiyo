"""Tests for shared Chat/Studio run snapshot projection."""

from __future__ import annotations

from typing import Any

from apps.shell.yachiyo_agent.run_snapshots import (
    RunSnapshotProjector,
    agent_task_snapshot_from_payload,
    run_timeline_snapshot_from_payload,
)
from apps.shell.yachiyo_agent.approvals import approval_card_from_payload
from apps.shell.yachiyo_agent.groups import group_run_snapshot_from_payload
from apps.shell.yachiyo_agent.legacy_runs import LegacyRunPayloadProjector
from apps.shell.yachiyo_agent.links import studio_run_url
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
    assert task.pending_approvals[0].open_in_studio_url == "#/agents?run_id=run-1&group_run=group-1"
    assert task.recent_events[0].event_type == "agent.tool.call"
    assert task.artifacts[0].source_run_id == "run-1"
    assert task.open_in_studio_url == "#/agents?run_id=run-1&group_run=group-1"

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


def test_studio_run_url_is_shared_by_run_task_and_approval_snapshots() -> None:
    run_id = "run with/slash"
    expected_url = "#/agents?run_id=run%20with%2Fslash"
    expected_group_url = "#/agents?run_id=run%20with%2Fslash&group_run=group%20with%2Fslash"

    assert studio_run_url(run_id) == expected_url
    assert studio_run_url(run_id, group_run_id="group with/slash") == expected_group_url
    assert studio_run_url("") is None

    task = agent_task_snapshot_from_payload({"run_id": run_id, "status": "completed"})
    approval = approval_card_from_payload({"tool": "workspace.read"}, run_id=run_id)
    grouped_task = agent_task_snapshot_from_payload({
        "run_id": run_id,
        "run_group_id": "group with/slash",
        "status": "approval_required",
        "pending_approval": {"tool": "workspace.write"},
    })
    grouped_approval = approval_card_from_payload(
        {"tool": "workspace.write"},
        run_id=run_id,
        group_run_id="group with/slash",
    )
    legacy_payload = LegacyRunPayloadProjector().chat_task_payload({"run_id": run_id})
    grouped_legacy_payload = LegacyRunPayloadProjector().chat_task_payload({
        "run_id": run_id,
        "run_group_id": "group with/slash",
    })

    assert task.open_in_studio_url == expected_url
    assert approval.open_in_studio_url == expected_url
    assert grouped_task.open_in_studio_url == expected_group_url
    assert grouped_task.pending_approvals[0].open_in_studio_url == expected_group_url
    assert grouped_approval.open_in_studio_url == expected_group_url
    assert legacy_payload["open_in_studio_url"] == expected_url
    assert grouped_legacy_payload["open_in_studio_url"] == expected_group_url


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
                        "group_id": "group-1",
                        "group_run_id": "group-run-1",
                        "member_agent_id": "agent-1",
                        "member_agent_name": "Planner",
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "workflow-run-1",
                        "workflow_node_id": "test",
                        "workflow_node_label": "Run Tests",
                        "input_preview": {"command": "npm test"},
                        "output_preview": {"approval_required": True},
                        "pending_approval": {
                            "approval_id": "approval-tool",
                            "risk_level": "high",
                            "policy_reason": "terminal command requires approval",
                        },
                    },
                },
                {
                    "event_type": "tool.approved",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                },
                {
                    "event_type": "tool.rejected",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "rm -rf /tmp/demo"},
                        "reason": "Too risky",
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
        "terminal.run",
        "terminal.run",
        "workspace.write",
    ]
    assert [call.status for call in timeline.tool_calls] == [
        "completed",
        "failed",
        "denied",
        "denied",
    ]
    assert timeline.tool_calls[0].input_preview == {"path": "README.md"}
    assert timeline.tool_calls[0].output_preview == {"ok": True}
    assert timeline.tool_calls[1].approval_id == "approval-tool"
    assert timeline.tool_calls[1].risk_level == "high"
    assert timeline.tool_calls[1].source_runnable_id == "agent-1"
    assert timeline.tool_calls[1].source_runnable_name == "Planner"
    assert timeline.tool_calls[1].workflow_id == "workflow-1"
    assert timeline.tool_calls[1].workflow_run_id == "workflow-run-1"
    assert timeline.tool_calls[1].workflow_node_id == "test"
    assert timeline.tool_calls[1].workflow_node_label == "Run Tests"
    assert timeline.tool_calls[1].group_id == "group-1"
    assert timeline.tool_calls[1].group_run_id == "group-run-1"
    assert timeline.tool_calls[1].input_preview == {
        "command": "npm test",
        "approval_id": "approval-tool",
        "risk_level": "high",
        "policy_reason": "terminal command requires approval",
        "group_id": "group-1",
        "group_run_id": "group-run-1",
        "member_agent_id": "agent-1",
        "member_agent_name": "Planner",
        "workflow_id": "workflow-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "test",
        "workflow_node_label": "Run Tests",
    }
    assert timeline.tool_calls[1].output_preview == {
        "approval_required": True,
        "error": "exit 1",
    }
    assert timeline.tool_calls[2].input_preview == {"command": "rm -rf /tmp/demo"}
    assert timeline.tool_calls[3].input_preview == {"path": "README.md"}
    assert all(call.run_id == "run-tools" for call in timeline.tool_calls)


def test_run_timeline_keeps_repeated_identical_tool_lifecycles_separate() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-repeated-tools",
            "status": "completed",
            "events": [
                {
                    "event_type": "tool.requested",
                    "payload": {"tool": "workspace.read", "input_preview": {"path": "README.md"}},
                },
                {
                    "event_type": "tool.completed",
                    "payload": {
                        "tool": "workspace.read",
                        "input_preview": {"path": "README.md"},
                        "output_preview": {"ok": True, "first": True},
                    },
                },
                {
                    "event_type": "tool.requested",
                    "payload": {"tool": "workspace.read", "input_preview": {"path": "README.md"}},
                },
                {
                    "event_type": "tool.completed",
                    "payload": {
                        "tool": "workspace.read",
                        "input_preview": {"path": "README.md"},
                        "output_preview": {"ok": True, "second": True},
                    },
                },
            ],
        }
    )

    assert [call.status for call in timeline.tool_calls] == ["completed", "completed"]
    assert timeline.tool_calls[0].output_preview == {"ok": True, "first": True}
    assert timeline.tool_calls[1].output_preview == {"ok": True, "second": True}


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


def test_run_timeline_preserves_memory_and_skill_trace_events() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-memory-skill",
            "status": "completed",
            "events": [
                {
                    "event_type": "memory.retrieved",
                    "payload": {
                        "count": 1,
                        "group_run_id": "group-run-1",
                        "memories": [
                            {
                                "memory_id": "memory-1",
                                "kind": "preference",
                                "scope": "global",
                            }
                        ],
                        "member_agent_id": "agent-researcher",
                        "member_agent_name": "Researcher",
                        "workflow_node_id": "retrieve-context",
                        "workflow_node_label": "Retrieve Context",
                    },
                },
                {
                    "event_type": "skill.selected",
                    "payload": {
                        "group_run_id": "group-run-1",
                        "member_agent_id": "agent-researcher",
                        "result": {
                            "skill_id": "skill-1",
                            "name": "Demo Skill",
                            "source_ref": "skills/demo/SKILL.md",
                        }
                    },
                },
                {
                    "event_type": "skill.dispatch.read",
                    "payload": {
                        "group_run_id": "group-run-1",
                        "member_agent_id": "agent-researcher",
                        "tool": "skill.read",
                        "status": "completed",
                        "workflow_node_id": "read-skill",
                        "workflow_node_label": "Read Skill",
                        "result": {
                            "skill_id": "skill-1",
                            "name": "Demo Skill",
                        },
                    },
                },
            ],
        }
    )

    assert [event.event_type for event in timeline.events] == [
        "memory.retrieved",
        "skill.selected",
        "skill.dispatch.read",
    ]
    assert timeline.events[0].payload["memories"][0]["memory_id"] == "memory-1"
    assert timeline.events[0].payload["memories"][0]["kind"] == "preference"
    assert timeline.events[0].payload["workflow_node_id"] == "retrieve-context"
    assert timeline.events[0].payload["member_agent_id"] == "agent-researcher"
    assert timeline.events[0].payload["group_run_id"] == "group-run-1"
    assert timeline.events[1].payload["result"]["skill_id"] == "skill-1"
    assert timeline.events[1].payload["result"]["source_ref"] == "skills/demo/SKILL.md"
    assert timeline.events[1].payload["member_agent_id"] == "agent-researcher"
    assert timeline.events[2].payload["tool"] == "skill.read"
    assert timeline.events[2].payload["status"] == "completed"
    assert timeline.events[2].payload["workflow_node_label"] == "Read Skill"
    assert timeline.tool_calls == []


def test_run_timeline_derives_approvals_and_artifacts_from_events() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-events-only",
            "status": "approval_required",
            "events": [
                {
                    "event_type": "tool.approval_required",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "status": "waiting_approval",
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                },
                {
                    "event_type": "workflow.node.approval_required",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "run-events-only",
                        "workflow_node_id": "review",
                        "workflow_node_label": "Review Gate",
                        "pending_approval": {
                            "approval_id": "approval-workflow",
                            "tool": "workflow.approval",
                            "input_preview": {"checkpoint": "Review Gate"},
                            "requested_at": "2026-06-15T00:00:01Z",
                        },
                    },
                },
                {
                    "event_type": "artifact.created",
                    "payload": {
                        "artifact_id": "artifact-tool",
                        "path": "notes.md",
                        "size_bytes": 9,
                        "source_tool": "artifact.write",
                    },
                    "created_at": "2026-06-15T00:00:02Z",
                },
                {
                    "event_type": "workflow.node.artifact",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "workflow-run-1",
                        "workflow_node_id": "report",
                        "workflow_node_label": "Report",
                        "artifact": {
                            "path": "workflow-report.md",
                            "bytes": 42,
                        },
                    },
                    "created_at": "2026-06-15T00:00:03Z",
                },
            ],
        }
    )

    assert timeline.pending_approval is not None
    assert timeline.pending_approval.tool_name == "terminal.run"
    assert [approval.tool_name for approval in timeline.approvals] == [
        "terminal.run",
        "workflow.approval",
    ]
    assert timeline.approvals[0].approval_id == "run-events-only:tool.approval_required:1"
    assert timeline.approvals[0].input_preview == {"command": "npm test"}
    assert timeline.approvals[1].approval_id == "approval-workflow"
    assert timeline.approvals[1].input_preview == {
        "checkpoint": "Review Gate",
        "workflow_id": "workflow-1",
        "workflow_run_id": "run-events-only",
        "workflow_node_id": "review",
        "workflow_node_label": "Review Gate",
    }
    assert [artifact.path for artifact in timeline.artifacts] == [
        "notes.md",
        "workflow-report.md",
    ]
    assert timeline.artifacts[0].kind == "artifact"
    assert timeline.artifacts[0].size_bytes == 9
    assert timeline.artifacts[0].source_tool == "artifact.write"
    assert timeline.artifacts[1].kind == "workflow_artifact"
    assert timeline.artifacts[1].title == "Report"
    assert timeline.artifacts[1].size_bytes == 42
    assert timeline.artifacts[1].workflow_id == "workflow-1"
    assert timeline.artifacts[1].workflow_run_id == "workflow-run-1"
    assert timeline.artifacts[1].workflow_node_id == "report"
    assert timeline.artifacts[1].workflow_node_label == "Report"


def test_run_timeline_merges_approval_lifecycle_events_into_stable_cards() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-approval-lifecycle",
            "status": "cancelled",
            "events": [
                {
                    "event_type": "tool.approval_required",
                    "payload": {
                        "pending_approval": {
                            "approval_id": "approval-terminal",
                            "tool": "terminal.run",
                            "input_preview": {"command": "npm test"},
                            "requested_at": "2026-06-15T00:00:00Z",
                        },
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                },
                {
                    "event_type": "agent.tool.approval_approved",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "status": "completed",
                    },
                    "created_at": "2026-06-15T00:00:01Z",
                },
                {
                    "event_type": "workflow.node.approval_required",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_node_id": "review",
                        "workflow_node_label": "Review Gate",
                        "pending_approval": {
                            "approval_id": "approval-workflow",
                            "tool": "workflow.approval",
                            "input_preview": {"checkpoint": "Review Gate"},
                        },
                    },
                    "created_at": "2026-06-15T00:00:02Z",
                },
                {
                    "event_type": "workflow.node.approval_rejected",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_node_id": "review",
                        "workflow_node_label": "Review Gate",
                        "input_preview": {"checkpoint": "Review Gate"},
                        "reason": "Needs more detail",
                    },
                    "created_at": "2026-06-15T00:00:03Z",
                },
            ],
        }
    )

    assert timeline.pending_approval is None
    assert [approval.approval_id for approval in timeline.approvals] == [
        "approval-terminal",
        "approval-workflow",
    ]
    assert [approval.status for approval in timeline.approvals] == ["approved", "rejected"]
    assert timeline.approvals[0].requested_at == "2026-06-15T00:00:00Z"
    assert timeline.approvals[0].resolved_at == "2026-06-15T00:00:01Z"
    assert timeline.approvals[0].input_preview == {"command": "npm test"}
    assert timeline.approvals[1].description == "Needs more detail"
    assert timeline.approvals[1].resolved_at == "2026-06-15T00:00:03Z"
    assert timeline.approvals[1].input_preview == {
        "checkpoint": "Review Gate",
        "workflow_id": "workflow-1",
        "workflow_node_id": "review",
        "workflow_node_label": "Review Gate",
    }


def test_run_timeline_projects_approval_timeout_as_expired_card() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-approval-timeout",
            "status": "cancelled",
            "events": [
                {
                    "event_type": "agent.tool.approval_required",
                    "payload": {
                        "approval_id": "approval-timeout",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                },
                {
                    "event_type": "approval.timeout",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "reason": "approval_wait_timeout",
                    },
                    "created_at": "2026-06-15T00:00:01Z",
                },
            ],
        }
    )

    assert len(timeline.approvals) == 1
    assert timeline.approvals[0].approval_id == "approval-timeout"
    assert timeline.approvals[0].status == "expired"
    assert timeline.approvals[0].description == "approval_wait_timeout"
    assert timeline.approvals[0].resolved_at == "2026-06-15T00:00:01Z"


def test_chat_task_snapshot_derives_approval_and_artifact_cards_from_events() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-events-only",
            "run_id": "run-task-events",
            "title": "Write notes",
            "status": "approval_required",
            "recent_events": [
                {
                    "event_type": "agent.tool.approval_required",
                    "payload": {
                        "approval_id": "approval-write",
                        "tool": "workspace.write",
                        "input_preview": {"path": "notes.md"},
                    },
                },
                {
                    "event_type": "artifact.created",
                    "payload": {
                        "path": "notes.md",
                        "size_bytes": 12,
                    },
                },
            ],
        }
    )

    assert task.status == "waiting_approval"
    assert task.needs_user_action is True
    assert task.pending_approvals[0].approval_id == "approval-write"
    assert task.pending_approvals[0].tool_name == "workspace.write"
    assert task.artifacts[0].path == "notes.md"
    assert task.artifacts[0].source_run_id == "run-task-events"


def test_chat_task_snapshot_ignores_resolved_approval_cards_for_user_action() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-approved",
            "run_id": "run-approved",
            "title": "Run tests",
            "status": "completed",
            "recent_events": [
                {
                    "event_type": "agent.tool.approval_required",
                    "payload": {
                        "approval_id": "approval-approved",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                },
                {
                    "event_type": "agent.tool.approval_approved",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                },
            ],
        }
    )

    assert task.status == "completed"
    assert task.needs_user_action is False
    assert task.pending_approvals == []


def test_group_run_snapshot_reuses_shared_run_projection_for_children_artifacts_and_approvals() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-1",
            "group_id": "group-1",
            "title": "Team review",
            "status": "running",
            "objective": "Compare options",
            "events": [
                {
                    "event_type": "group.member.started",
                    "detail": "Planner started",
                    "payload": {"member_agent_id": "agent-1"},
                }
            ],
            "runs": [_run_payload()],
            "shared_artifacts": [{"kind": "markdown", "path": "team.md"}],
            "pending_approvals": [{"approval_id": "approval-group", "tool": "terminal.run"}],
        }
    )

    assert group_run.group_run_id == "group-run-1"
    assert [event.event_type for event in group_run.events[:2]] == [
        "group.run.started",
        "group.member.started",
    ]
    assert group_run.events[0].payload["group_run_id"] == "group-run-1"
    assert group_run.events[0].payload["group_id"] == "group-1"
    assert group_run.events[0].payload["objective"] == "Compare options"
    assert group_run.events[1].payload["member_agent_id"] == "agent-1"
    assert group_run.runs[0].run_id == "run-1"
    assert group_run.runs[0].tool_calls[0].tool_name == "workspace.read"
    assert group_run.runs[0].pending_approval is not None
    assert group_run.shared_artifacts[0].source_run_id == "group-run-1"
    assert group_run.shared_artifacts[0].path == "team.md"
    assert group_run.pending_approvals[0].run_id == "group-run-1"
    assert group_run.pending_approvals[0].open_in_studio_url == "#/agents?run_id=group-run-1&group_run=group-run-1"


def test_legacy_group_run_payload_collects_child_group_events_for_replay() -> None:
    runtime = _FakeLegacyGroupRuntime()
    payload = LegacyRunPayloadProjector().group_run_from_legacy_run_group(
        {
            "run_group_id": "group-run-legacy",
            "title": "Team review",
            "status": "running",
            "summary": "Compare options",
            "child_run_ids": ["run-1", "run-2"],
        },
        runtime,
    )
    group_run = group_run_snapshot_from_payload(payload)

    assert [event["event_type"] for event in payload["events"]] == [
        "group.member.started",
        "group.member.completed",
    ]
    assert [event.event_type for event in group_run.events[:3]] == [
        "group.run.started",
        "group.member.started",
        "group.member.completed",
    ]
    assert [event.sequence for event in group_run.events[:3]] == [1, 2, 3]
    assert group_run.events[1].run_id == "run-1"
    assert group_run.events[1].payload["member_agent_id"] == "agent-1"
    assert group_run.events[1].payload["source_run_id"] == "run-1"
    assert group_run.events[1].payload["source_sequence"] == 7
    assert group_run.events[2].run_id == "run-2"
    assert group_run.events[2].payload["source_run_id"] == "run-2"
    assert group_run.events[2].payload["source_sequence"] == 3
    assert runtime.event_calls == ["run-1", "run-2"]


def test_group_run_snapshot_renumbers_child_run_events_for_group_replay() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-1",
            "status": "running",
            "events": [
                {
                    "event_type": "group.run.started",
                    "run_id": "child-run-1",
                    "sequence": 9,
                    "payload": {"run_group_id": "group-run-1"},
                },
                {
                    "event_type": "group.member.completed",
                    "run_id": "child-run-2",
                    "sequence": 1,
                    "payload": {"member_agent_id": "agent-2"},
                },
            ],
        }
    )

    assert [event.sequence for event in group_run.events] == [1, 2]
    assert group_run.events[0].payload["source_run_id"] == "child-run-1"
    assert group_run.events[0].payload["source_sequence"] == 9
    assert group_run.events[1].payload["source_run_id"] == "child-run-2"
    assert group_run.events[1].payload["source_sequence"] == 1


def test_group_run_snapshot_falls_back_to_legacy_event_keys_when_events_is_empty() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-legacy-events",
            "group_id": "group-1",
            "status": "running",
            "events": [],
            "run_events": [
                {
                    "event_type": "group.member.started",
                    "payload": {"member_agent_id": "agent-1"},
                }
            ],
        }
    )

    assert [event.event_type for event in group_run.events[:2]] == [
        "group.run.started",
        "group.member.started",
    ]


def test_group_run_snapshot_derives_approvals_and_artifacts_from_group_events() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-events-only",
            "group_id": "group-1",
            "title": "Team review",
            "status": "approval_required",
            "objective": "Compare options",
            "events": [
                {
                    "event_type": "group.approval_required",
                    "payload": {
                        "group_id": "group-1",
                        "member_agent_id": "agent-1",
                        "member_agent_name": "Planner",
                        "pending_approval": {
                            "approval_id": "approval-group-event",
                            "input_preview": {"decision": "continue"},
                        },
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                },
                {
                    "event_type": "group.shared_artifact.created",
                    "payload": {
                        "member_agent_id": "agent-1",
                        "member_agent_name": "Planner",
                        "artifact": {
                            "path": "team-summary.md",
                            "bytes": 33,
                        },
                    },
                    "created_at": "2026-06-15T00:00:01Z",
                },
            ],
        }
    )

    assert [event.event_type for event in group_run.events[:2]] == [
        "group.run.started",
        "group.approval_required",
    ]
    assert group_run.pending_approvals[0].approval_id == "approval-group-event"
    assert group_run.pending_approvals[0].tool_name == "group.approval"
    assert group_run.pending_approvals[0].title == "Approve Planner"
    assert group_run.pending_approvals[0].input_preview == {
        "decision": "continue",
        "group_id": "group-1",
        "group_run_id": "group-events-only",
        "member_agent_id": "agent-1",
        "member_agent_name": "Planner",
    }
    assert group_run.shared_artifacts[0].kind == "group_artifact"
    assert group_run.shared_artifacts[0].title == "Planner / team-summary.md"
    assert group_run.shared_artifacts[0].path == "team-summary.md"
    assert group_run.shared_artifacts[0].size_bytes == 33
    assert group_run.shared_artifacts[0].source_run_id == "group-events-only"
    assert group_run.shared_artifacts[0].source_runnable_id == "agent-1"
    assert group_run.shared_artifacts[0].source_runnable_name == "Planner"
    assert group_run.shared_artifacts[0].group_id == "group-1"
    assert group_run.shared_artifacts[0].group_run_id == "group-events-only"


def test_group_run_snapshot_adds_terminal_lifecycle_event_from_status() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-completed",
            "group_id": "group-1",
            "title": "Team review",
            "status": "completed",
            "objective": "Compare options",
            "child_run_ids": ["run-1"],
            "events": [
                {
                    "event_type": "group.member.completed",
                    "payload": {"member_agent_id": "agent-1"},
                },
            ],
        }
    )

    assert [event.event_type for event in group_run.events] == [
        "group.run.started",
        "group.member.completed",
        "group.run.completed",
    ]
    assert group_run.events[-1].payload["status"] == "completed"
    assert group_run.events[-1].payload["child_run_ids"] == ["run-1"]


class _FakeLegacyGroupRuntime:
    def __init__(self) -> None:
        self.event_calls: list[str] = []
        self.runs = {
            "run-1": {
                "run_id": "run-1",
                "runnable_id": "agent-1",
                "runnable_name": "Planner",
                "status": "running",
                "timeline": [{"event": "agent.run.started"}],
            },
            "run-2": {
                "run_id": "run-2",
                "runnable_id": "agent-2",
                "runnable_name": "Reviewer",
                "status": "completed",
                "timeline": [{"event": "group.member.completed"}],
            },
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        return dict(self.runs[run_id])

    def list_run_events(self, run_id: str) -> dict[str, Any]:
        self.event_calls.append(run_id)
        if run_id == "run-1":
            return {
                "events": [
                    {
                        "event_type": "group.member.started",
                        "sequence": 7,
                        "payload": {"member_agent_id": "agent-1"},
                    },
                    {
                        "event_type": "agent.tool.call",
                        "payload": {"tool": "workspace.read"},
                    },
                ]
            }
        return {
            "events": [
                {
                    "event_type": "group.member.completed",
                    "sequence": 3,
                    "payload": {"member_agent_id": "agent-2"},
                }
            ]
        }
