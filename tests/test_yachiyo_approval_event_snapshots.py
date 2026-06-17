"""Approval snapshot mapper regressions for replayed RunEvents."""

from __future__ import annotations

from apps.shell.yachiyo_agent.approval_event_snapshots import approval_snapshots_from_events
from apps.shell.yachiyo_agent.contracts import PublicRunEvent


def test_approval_event_mapper_merges_pending_and_resolution_events() -> None:
    approvals = approval_snapshots_from_events(
        [
            PublicRunEvent(
                run_id="run-1",
                sequence=1,
                event_type="tool.approval_required",
                created_at="2026-06-15T00:00:00Z",
                payload={
                    "pending_approval": {
                        "approval_id": "approval-1",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "policy_reason": "terminal command requires approval",
                    },
                },
            ),
            PublicRunEvent(
                run_id="run-1",
                sequence=2,
                event_type="tool.approved",
                created_at="2026-06-15T00:00:01Z",
                payload={
                    "approval_id": "approval-1",
                    "tool": "terminal.run",
                },
            ),
            PublicRunEvent(
                run_id="run-1",
                sequence=3,
                event_type="tool.approval_required",
                sensitivity="secret",
                payload={
                    "pending_approval": {
                        "approval_id": "approval-secret",
                        "tool": "terminal.run",
                    },
                },
            ),
        ]
    )

    assert len(approvals) == 1
    assert approvals[0].approval_id == "approval-1"
    assert approvals[0].status == "approved"
    assert approvals[0].input_preview == {"command": "npm test"}
    assert approvals[0].policy_reason == "terminal command requires approval"
    assert approvals[0].requested_at == "2026-06-15T00:00:00Z"
    assert approvals[0].resolved_at == "2026-06-15T00:00:01Z"


def test_approval_event_mapper_projects_workflow_group_context() -> None:
    approvals = approval_snapshots_from_events(
        [
            PublicRunEvent(
                run_id="workflow-run-1",
                sequence=1,
                event_type="workflow.node.approval_required",
                created_at="2026-06-15T00:00:00Z",
                payload={
                    "group_id": "group-1",
                    "member_agent_id": "agent-reviewer",
                    "member_agent_name": "Reviewer",
                    "workflow_id": "workflow-1",
                    "workflow_run_id": "workflow-run-1",
                    "workflow_node_id": "review",
                    "workflow_node_label": "Review Gate",
                    "pending_approval": {
                        "approval_id": "approval-workflow",
                        "input_preview": {"notes": "needs review"},
                    },
                },
            )
        ],
        group_run_id="group-run-1",
    )

    assert len(approvals) == 1
    approval = approvals[0]
    assert approval.tool_name == "workflow.approval"
    assert approval.title == "Approve Review Gate"
    assert approval.source_runnable_id == "agent-reviewer"
    assert approval.source_runnable_name == "Reviewer"
    assert approval.workflow_id == "workflow-1"
    assert approval.workflow_run_id == "workflow-run-1"
    assert approval.workflow_node_id == "review"
    assert approval.workflow_node_label == "Review Gate"
    assert approval.group_id == "group-1"
    assert approval.group_run_id == "group-run-1"
    assert approval.input_preview == {
        "notes": "needs review",
        "group_id": "group-1",
        "group_run_id": "group-run-1",
        "member_agent_id": "agent-reviewer",
        "member_agent_name": "Reviewer",
        "workflow_id": "workflow-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "review",
        "workflow_node_label": "Review Gate",
    }
