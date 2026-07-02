"""Approval public snapshot merge helpers."""

from __future__ import annotations

from .contracts import ApprovalCardSnapshot


def merge_approval_snapshots(
    current: ApprovalCardSnapshot,
    next_approval: ApprovalCardSnapshot,
) -> ApprovalCardSnapshot:
    return ApprovalCardSnapshot(
        approval_id=current.approval_id or next_approval.approval_id,
        run_id=current.run_id or next_approval.run_id,
        source_run_id=current.source_run_id or next_approval.source_run_id,
        source_runnable_id=current.source_runnable_id or next_approval.source_runnable_id,
        source_runnable_name=current.source_runnable_name or next_approval.source_runnable_name,
        workflow_id=current.workflow_id or next_approval.workflow_id,
        workflow_run_id=current.workflow_run_id or next_approval.workflow_run_id,
        workflow_node_id=current.workflow_node_id or next_approval.workflow_node_id,
        workflow_node_label=current.workflow_node_label or next_approval.workflow_node_label,
        group_id=current.group_id or next_approval.group_id,
        group_run_id=current.group_run_id or next_approval.group_run_id,
        core_id=current.core_id or next_approval.core_id,
        workspace_id=current.workspace_id or next_approval.workspace_id,
        task_id=current.task_id or next_approval.task_id,
        source=current.source or next_approval.source,
        planning_reason=current.planning_reason or next_approval.planning_reason,
        step_id=current.step_id or next_approval.step_id,
        planner_step_id=current.planner_step_id or next_approval.planner_step_id,
        capability_id=current.capability_id or next_approval.capability_id,
        decision_id=current.decision_id or next_approval.decision_id,
        plan_id=current.plan_id or next_approval.plan_id,
        tool_plan_id=current.tool_plan_id or next_approval.tool_plan_id,
        intent_kind=current.intent_kind or next_approval.intent_kind,
        replan_request_id=current.replan_request_id or next_approval.replan_request_id,
        replan_trigger=current.replan_trigger or next_approval.replan_trigger,
        title=current.title or next_approval.title,
        description=next_approval.description or current.description,
        status=next_approval.status or current.status,
        tool_name=current.tool_name or next_approval.tool_name,
        risk_level=current.risk_level or next_approval.risk_level,
        input_preview={**current.input_preview, **next_approval.input_preview},
        policy_reason=current.policy_reason or next_approval.policy_reason,
        requested_at=current.requested_at or next_approval.requested_at,
        resolved_at=next_approval.resolved_at or current.resolved_at,
        open_in_studio_url=current.open_in_studio_url or next_approval.open_in_studio_url,
    )


def merge_approval_snapshot_lists(
    *approval_lists: list[ApprovalCardSnapshot],
) -> list[ApprovalCardSnapshot]:
    by_key = {}
    ordered_keys = []
    for approvals in approval_lists:
        for approval in approvals or []:
            key = approval.approval_id or approval.run_id or approval.title
            if not key:
                continue
            if key not in by_key:
                by_key[key] = approval
                ordered_keys.append(key)
            else:
                by_key[key] = merge_approval_snapshots(by_key[key], approval)
    return [by_key[key] for key in ordered_keys]
