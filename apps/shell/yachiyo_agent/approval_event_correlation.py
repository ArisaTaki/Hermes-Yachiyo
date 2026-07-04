"""Approval RunEvent lifecycle correlation helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .contracts import ApprovalCardSnapshot

_AMBIGUOUS_APPROVAL_INDEX = -1


class ApprovalEventCorrelationTracker:
    """Tracks active approval events while replaying a run timeline."""

    def __init__(self) -> None:
        self._active_by_strong_key: dict[str, int] = {}
        self._active_by_weak_key: dict[str, int] = {}
        self._active_keys_by_index: dict[int, tuple[list[str], str]] = {}

    def active_index(
        self,
        strong_keys: list[str],
        weak_key: str,
        *,
        allow_weak: bool,
    ) -> int | None:
        for key in strong_keys:
            if key in self._active_by_strong_key:
                return self._active_by_strong_key[key]
        if not allow_weak:
            return None
        weak_index = self._active_by_weak_key.get(weak_key) if weak_key else None
        if weak_index is not None and weak_index != _AMBIGUOUS_APPROVAL_INDEX:
            return weak_index
        return None

    def register_pending(self, index: int, strong_keys: list[str], weak_key: str) -> None:
        for key in strong_keys:
            self._active_by_strong_key[key] = index
        if weak_key:
            existing = self._active_by_weak_key.get(weak_key)
            if existing is None:
                self._active_by_weak_key[weak_key] = index
            elif existing != index:
                self._active_by_weak_key[weak_key] = _AMBIGUOUS_APPROVAL_INDEX
        self._active_keys_by_index[index] = (strong_keys, weak_key)

    def unregister(self, index: int) -> None:
        strong_keys, weak_key = self._active_keys_by_index.pop(index, ([], ""))
        for key in strong_keys:
            if self._active_by_strong_key.get(key) == index:
                self._active_by_strong_key.pop(key, None)
        if weak_key and self._active_by_weak_key.get(weak_key) == index:
            self._active_by_weak_key.pop(weak_key, None)


def approval_correlation_keys(
    payload: Mapping[str, Any],
    approval: ApprovalCardSnapshot,
) -> tuple[list[str], str]:
    run_id = approval.run_id or _text(payload.get("run_id"))
    tool_name = approval.tool_name or _text(payload.get("tool") or payload.get("tool_name"))
    preview = _approval_correlation_preview(approval.input_preview)
    workflow_node_id = _text(
        payload.get("workflow_node_id")
        or approval.workflow_node_id
        or approval.input_preview.get("workflow_node_id")
    )
    group_run_id = _text(
        payload.get("group_run_id")
        or payload.get("run_group_id")
        or approval.group_run_id
        or approval.input_preview.get("group_run_id")
        or approval.input_preview.get("run_group_id")
    )
    source_runnable_id = _text(
        payload.get("source_runnable_id")
        or payload.get("member_agent_id")
        or payload.get("agent_id")
        or approval.source_runnable_id
        or approval.input_preview.get("source_runnable_id")
        or approval.input_preview.get("member_agent_id")
        or approval.input_preview.get("agent_id")
    )

    base_parts = [
        run_id,
        "approval",
        tool_name,
        workflow_node_id,
        group_run_id,
        source_runnable_id,
    ]
    strong_keys = []

    explicit_id = _text(
        payload.get("approval_id")
        or payload.get("id")
        or payload.get("approval_signature")
        or approval.approval_id
    )
    if explicit_id:
        strong_keys.append(f"{run_id}:approval_id:{explicit_id}")
    if tool_name or workflow_node_id or group_run_id or source_runnable_id or preview:
        strong_keys.append(":".join([*base_parts, _stable_json(preview)]))
    weak_key = ":".join(base_parts) if any(base_parts[2:]) else ""
    return list(dict.fromkeys(strong_keys)), weak_key


def _approval_correlation_preview(preview: Mapping[str, Any]) -> dict[str, Any]:
    trace_keys = {
        "agent_id",
        "agent_name",
        "approval_id",
        "app_resolution_confidence",
        "app_resolution_reason",
        "app_resolution_score",
        "app_resolution_source",
        "app_selection_source",
        "capability_id",
        "core_id",
        "decision_id",
        "deferred_context",
        "deferred_continuation",
        "deferred_input",
        "deferred_tool",
        "group_id",
        "group_run_id",
        "intent_kind",
        "member_agent_id",
        "member_agent_name",
        "plan_id",
        "planner_step_id",
        "planning_reason",
        "policy_reason",
        "risk_level",
        "run_id",
        "run_group_id",
        "runtime_doctrine",
        "runtime_role",
        "runtime_stage",
        "replan_request_id",
        "replan_signal_ids",
        "replan_trigger",
        "replan_triggers",
        "requires_observation",
        "requires_post_action_verification",
        "resolved_app_name",
        "resolved_app_path",
        "requested_app_name",
        "selection_source",
        "source",
        "source_agent_id",
        "source_agent_name",
        "source_run_id",
        "source_runnable_id",
        "source_runnable_name",
        "source_tool",
        "step_id",
        "task_id",
        "tool_plan_id",
        "tool_call_id",
        "workspace_id",
        "workflow_id",
        "workflow_node_id",
        "workflow_node_kind",
        "workflow_node_label",
        "workflow_run_id",
        "workflow_step_label",
    }
    return {key: value for key, value in preview.items() if key not in trace_keys}


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()
