"""Approval public snapshot merge helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

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
        replan_triggers=_merge_string_lists(
            current.replan_triggers,
            next_approval.replan_triggers,
        ),
        replan_signal_ids=_merge_string_lists(
            current.replan_signal_ids,
            next_approval.replan_signal_ids,
        ),
        runtime_doctrine=current.runtime_doctrine or next_approval.runtime_doctrine,
        runtime_stage=current.runtime_stage or next_approval.runtime_stage,
        runtime_role=current.runtime_role or next_approval.runtime_role,
        requires_observation=(
            current.requires_observation or next_approval.requires_observation
        ),
        requires_post_action_verification=(
            current.requires_post_action_verification
            or next_approval.requires_post_action_verification
        ),
        deferred_tool=current.deferred_tool or next_approval.deferred_tool,
        deferred_input={**next_approval.deferred_input, **current.deferred_input},
        deferred_context={**next_approval.deferred_context, **current.deferred_context},
        deferred_continuation=_merge_record_lists(
            current.deferred_continuation,
            next_approval.deferred_continuation,
        ),
        action_target=_merge_mappings(
            current.action_target,
            next_approval.action_target,
        ),
        observation_evidence=_merge_mappings(
            current.observation_evidence,
            next_approval.observation_evidence,
        ),
        observation_retry=_merge_mappings(
            current.observation_retry,
            next_approval.observation_retry,
        ),
        task_workspace_items=_merge_record_lists(
            current.task_workspace_items,
            next_approval.task_workspace_items,
        ),
        verification_targets=_merge_record_lists(
            current.verification_targets,
            next_approval.verification_targets,
        ),
        task_verification_targets=_merge_record_lists(
            current.task_verification_targets,
            next_approval.task_verification_targets,
        ),
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


def _merge_mappings(
    current: dict[str, Any],
    next_items: dict[str, Any],
) -> dict[str, Any]:
    return {**dict(current or {}), **dict(next_items or {})}


def _merge_record_lists(
    current: list[dict[str, Any]],
    next_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*current, *next_items]:
        if not isinstance(item, Mapping):
            continue
        record = dict(item)
        try:
            key = json.dumps(record, ensure_ascii=True, sort_keys=True, default=str)
        except (TypeError, ValueError):
            key = str(record)
        if key in seen:
            continue
        seen.add(key)
        merged.append(record)
    return merged


def _merge_string_lists(current: list[str], next_items: list[str]) -> list[str]:
    result: list[str] = []
    for item in [*current, *next_items]:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result
