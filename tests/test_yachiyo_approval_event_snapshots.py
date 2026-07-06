"""Approval snapshot mapper regressions for replayed RunEvents."""

from __future__ import annotations

from apps.shell.yachiyo_agent.approval_event_snapshots import (
    approval_snapshots_from_events,
    merge_approval_snapshot_lists,
)
from apps.shell.yachiyo_agent.approvals import approval_card_from_payload
from apps.shell.yachiyo_agent.contracts import ApprovalCardSnapshot, PublicRunEvent


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
                        "task_workspace_items": [
                            {"item_id": "workspace-report", "title": "Report", "path": "report.md"}
                        ],
                        "task_verification_targets": [
                            {
                                "todo_id": "todo-report",
                                "todo_title": "Review report",
                                "workspace_items": [
                                    {"item_id": "workspace-report", "path": "report.md"}
                                ],
                            }
                        ],
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
    assert approvals[0].task_workspace_items == [
        {"item_id": "workspace-report", "title": "Report", "path": "report.md"}
    ]
    assert approvals[0].task_verification_targets == [
        {
            "todo_id": "todo-report",
            "todo_title": "Review report",
            "workspace_items": [
                {"item_id": "workspace-report", "path": "report.md"}
            ],
        }
    ]
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
                    "core_id": "core-1",
                    "workspace_id": "workspace-1",
                    "task_id": "task-1",
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
    assert approval.core_id == "core-1"
    assert approval.workspace_id == "workspace-1"
    assert approval.task_id == "task-1"
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
        "core_id": "core-1",
        "workspace_id": "workspace-1",
        "task_id": "task-1",
    }


def test_approval_event_mapper_uses_top_level_run_context() -> None:
    approvals = approval_snapshots_from_events(
        [
            PublicRunEvent(
                run_id="child-run-1",
                sequence=1,
                event_type="workflow.node.approval_required",
                created_at="2026-06-15T00:00:00Z",
                source_runnable_id="agent-reviewer",
                source_runnable_name="Reviewer",
                workflow_id="workflow-1",
                workflow_run_id="workflow-run-1",
                workflow_node_id="review",
                workflow_node_label="Review Gate",
                group_id="group-1",
                group_run_id="group-run-1",
                core_id="core-1",
                workspace_id="workspace-1",
                task_id="task-1",
                payload={
                    "pending_approval": {
                        "approval_id": "approval-top-level-context",
                        "input_preview": {"notes": "needs review"},
                    },
                },
            )
        ]
    )

    assert len(approvals) == 1
    approval = approvals[0]
    assert approval.source_runnable_id == "agent-reviewer"
    assert approval.source_runnable_name == "Reviewer"
    assert approval.workflow_id == "workflow-1"
    assert approval.workflow_run_id == "workflow-run-1"
    assert approval.workflow_node_id == "review"
    assert approval.workflow_node_label == "Review Gate"
    assert approval.group_id == "group-1"
    assert approval.group_run_id == "group-run-1"
    assert approval.core_id == "core-1"
    assert approval.workspace_id == "workspace-1"
    assert approval.task_id == "task-1"
    assert approval.input_preview["workflow_run_id"] == "workflow-run-1"
    assert approval.input_preview["group_run_id"] == "group-run-1"
    assert approval.input_preview["core_id"] == "core-1"
    assert approval.input_preview["workspace_id"] == "workspace-1"
    assert approval.input_preview["task_id"] == "task-1"


def test_approval_event_mapper_projects_scoped_desktop_intent_approval() -> None:
    approvals = approval_snapshots_from_events(
        [
            PublicRunEvent(
                run_id="workflow-run-desktop",
                sequence=1,
                event_type="workflow.run.desktop.intent_approval_required",
                created_at="2026-06-27T00:00:00Z",
                payload={
                    "tool": "desktop.hotkey",
                    "approval_id": "approval-hotkey",
                    "risk_level": "medium",
                    "policy_reason": "前台快捷键需要确认。",
                    "workflow_id": "workflow-1",
                    "workflow_run_id": "workflow-run-1",
                    "workflow_node_id": "desktop",
                    "workflow_node_label": "Desktop Action",
                    "group_id": "group-1",
                    "group_run_id": "group-run-1",
                    "input_preview": {"key": "l", "modifiers": ["command"]},
                },
            )
        ]
    )

    assert len(approvals) == 1
    approval = approvals[0]
    assert approval.approval_id == "approval-hotkey"
    assert approval.status == "pending"
    assert approval.tool_name == "desktop.hotkey"
    assert approval.workflow_run_id == "workflow-run-1"
    assert approval.workflow_node_id == "desktop"
    assert approval.group_run_id == "group-run-1"
    assert approval.input_preview["key"] == "l"
    assert approval.input_preview["workflow_run_id"] == "workflow-run-1"
    assert approval.input_preview["group_run_id"] == "group-run-1"


def test_merge_approval_snapshot_lists_preserves_order_and_fills_resolution() -> None:
    pending = approval_card_from_payload(
        {
            "approval_id": "approval-1",
            "tool": "terminal.run",
            "input_preview": {"command": "npm test"},
            "runtime_execution_envelope": {
                "envelope_id": "approval-envelope-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "intent_kind": "code_task",
                "requests": [
                    {
                        "request_id": "request-1",
                        "tool_name": "terminal.run",
                        "risk_level": "high",
                    }
                ],
            },
            "runtime_execution_metadata": {"yachiyo_runtime_planner": True},
            "created_at": "2026-06-15T00:00:00Z",
        },
        run_id="run-1",
    )
    resolved = approval_card_from_payload(
        {
            "approval_id": "approval-1",
            "tool": "terminal.run",
            "status": "approved",
            "resolved_at": "2026-06-15T00:00:01Z",
        },
        run_id="run-1",
    )
    second = approval_card_from_payload(
        {"approval_id": "approval-2", "tool": "workspace.write"},
        run_id="run-1",
    )

    merged = merge_approval_snapshot_lists([pending, second], [resolved])

    assert [approval.approval_id for approval in merged] == ["approval-1", "approval-2"]
    assert merged[0].status == "approved"
    assert merged[0].requested_at == "2026-06-15T00:00:00Z"
    assert merged[0].resolved_at == "2026-06-15T00:00:01Z"
    assert merged[0].input_preview == {"command": "npm test"}
    assert merged[0].runtime_execution_envelope is not None
    assert merged[0].runtime_execution_envelope.envelope_id == "approval-envelope-1"
    assert merged[0].runtime_execution_metadata == {"yachiyo_runtime_planner": True}


def test_merge_approval_snapshot_lists_skips_empty_identity_snapshots() -> None:
    anonymous = ApprovalCardSnapshot(
        approval_id="",
        title="",
        status="pending",
    )

    assert merge_approval_snapshot_lists([anonymous]) == []
