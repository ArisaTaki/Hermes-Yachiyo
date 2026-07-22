"""Approval public snapshot merge helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.approval_snapshots import approval_executable_input

from .contracts import ApprovalCardSnapshot


_APPROVAL_ACTION_TRACE_KEYS = {
    "action_target",
    "approval_id",
    "approval_required",
    "capability_id",
    "core_id",
    "decision_id",
    "deferred_context",
    "deferred_continuation",
    "depends_on",
    "desktop_execution_policy",
    "desktop_loop",
    "followup_target",
    "input_resolution",
    "intent_kind",
    "observation_evidence",
    "observation_retry",
    "plan_id",
    "planner_step_id",
    "planning_reason",
    "policy_reason",
    "replan_request_id",
    "replan_signal_ids",
    "replan_trigger",
    "replan_triggers",
    "request_id",
    "requires_approval",
    "requires_observation",
    "requires_post_action_verification",
    "risk_level",
    "run_id",
    "runtime_doctrine",
    "runtime_role",
    "runtime_stage",
    "selection_source",
    "source",
    "source_tool",
    "step_id",
    "target_app_name",
    "target_app_query",
    "task_checkpoints",
    "task_id",
    "task_todo",
    "task_verification_targets",
    "task_workspace_items",
    "tool_call_id",
    "tool_plan_id",
    "verification_targets",
    "workspace_id",
}


def merge_approval_snapshots(
    current: ApprovalCardSnapshot,
    next_approval: ApprovalCardSnapshot,
) -> ApprovalCardSnapshot:
    return ApprovalCardSnapshot(
        approval_id=_preferred_approval_id(current, next_approval),
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
        runtime_execution_envelope=(
            current.runtime_execution_envelope
            or next_approval.runtime_execution_envelope
        ),
        runtime_execution_metadata=_merge_mappings(
            current.runtime_execution_metadata,
            next_approval.runtime_execution_metadata,
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
        status=_merged_approval_status(current.status, next_approval.status),
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
    merged: list[ApprovalCardSnapshot] = []
    indexes_by_id: dict[str, int] = {}
    indexes_by_signature: dict[str, list[int]] = {}
    for approvals in approval_lists:
        for approval in approvals or []:
            approval_id = str(approval.approval_id or "").strip()
            signature = approval_canonical_signature(approval)
            if not approval_id and not signature:
                continue
            merge_index = indexes_by_id.get(approval_id) if approval_id else None
            if merge_index is None and signature:
                for candidate_index in reversed(indexes_by_signature.get(signature, [])):
                    if _approval_snapshots_can_merge_by_signature(
                        merged[candidate_index],
                        approval,
                    ):
                        merge_index = candidate_index
                        break
            if merge_index is None:
                merge_index = len(merged)
                merged.append(approval)
            else:
                merged[merge_index] = merge_approval_snapshots(
                    merged[merge_index],
                    approval,
                )
            for identity in {
                approval_id,
                str(merged[merge_index].approval_id or "").strip(),
            }:
                if identity:
                    indexes_by_id[identity] = merge_index
            if signature:
                signature_indexes = indexes_by_signature.setdefault(signature, [])
                if merge_index not in signature_indexes:
                    signature_indexes.append(merge_index)
    return merged


def approval_canonical_signature(approval: ApprovalCardSnapshot) -> str:
    """Identity for one approval action across payload and RunEvent projections."""

    run_id = str(approval.run_id or "").strip()
    plan_id = str(approval.plan_id or "").strip()
    step_id = str(approval.step_id or approval.planner_step_id or "").strip()
    tool_name = str(approval.tool_name or "").strip()
    if not run_id or not plan_id or not step_id or not tool_name:
        return ""
    # The same approval can be projected once from the broker-owned pending
    # request and again from a richer runtime event.  Event previews also carry
    # provider/readiness diagnostics that are not part of the action itself.
    # Project through the broker descriptor before comparing so those two
    # representations share one semantic identity.
    action_input = _canonical_approval_action_input(
        approval_executable_input(tool_name, approval.input_preview)
    )
    return _stable_json([run_id, plan_id, step_id, tool_name, action_input])


def _canonical_approval_action_input(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_approval_action_input(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _APPROVAL_ACTION_TRACE_KEYS
        }
    if isinstance(value, list):
        return [_canonical_approval_action_input(item) for item in value]
    return value


def _approval_snapshots_can_merge_by_signature(
    current: ApprovalCardSnapshot,
    next_approval: ApprovalCardSnapshot,
) -> bool:
    current_id = str(current.approval_id or "").strip()
    next_id = str(next_approval.approval_id or "").strip()
    if current_id and next_id and current_id != next_id:
        current_fallback = _approval_id_is_event_fallback(current)
        next_fallback = _approval_id_is_event_fallback(next_approval)
        if not current_fallback and not next_fallback:
            return False
        if _resolved_approval_precedes_new_pending(current, next_approval):
            return False
        if _resolved_approval_precedes_new_pending(next_approval, current):
            return False
    return True


def _preferred_approval_id(
    current: ApprovalCardSnapshot,
    next_approval: ApprovalCardSnapshot,
) -> str:
    current_id = str(current.approval_id or "").strip()
    next_id = str(next_approval.approval_id or "").strip()
    if current_id and next_id:
        if _approval_id_is_event_fallback(current) and not _approval_id_is_event_fallback(
            next_approval
        ):
            return next_id
        if _approval_id_is_event_fallback(next_approval) and not _approval_id_is_event_fallback(
            current
        ):
            return current_id
    return current_id or next_id


def _approval_id_is_event_fallback(approval: ApprovalCardSnapshot) -> bool:
    approval_id = str(approval.approval_id or "").strip()
    run_id = str(approval.run_id or "").strip()
    if not approval_id or not run_id or not approval_id.startswith(f"{run_id}:"):
        return False
    event_identity = approval_id[len(run_id) + 1 :]
    return "approval" in event_identity


def _resolved_approval_precedes_new_pending(
    resolved: ApprovalCardSnapshot,
    pending: ApprovalCardSnapshot,
) -> bool:
    if str(resolved.status or "").strip() == "pending":
        return False
    if str(pending.status or "").strip() != "pending":
        return False
    resolved_at = str(resolved.resolved_at or "").strip()
    requested_at = str(pending.requested_at or "").strip()
    return bool(resolved_at and requested_at and resolved_at < requested_at)


def _merged_approval_status(current: str, next_status: str) -> str:
    clean_current = str(current or "").strip()
    clean_next = str(next_status or "").strip()
    if clean_next and clean_next != "pending":
        return clean_next
    if clean_current and clean_current != "pending":
        return clean_current
    return clean_next or clean_current or "pending"


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


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
