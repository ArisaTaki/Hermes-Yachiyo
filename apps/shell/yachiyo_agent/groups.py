"""Agent group and group run public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import AgentGroupMemberSnapshot, AgentGroupSnapshot, GroupRunSnapshot
from .run_snapshots import RunSnapshotProjector


_RUN_PROJECTOR = RunSnapshotProjector()


def agent_group_snapshot_from_payload(
    payload: Mapping[str, Any] | AgentGroupSnapshot,
) -> AgentGroupSnapshot:
    if isinstance(payload, AgentGroupSnapshot):
        return payload

    return AgentGroupSnapshot(
        group_id=_text(payload.get("group_id") or payload.get("agent_group_id")),
        name=_text(payload.get("name") or "Agent Group"),
        description=_optional_text(payload.get("description")),
        members=agent_group_members_from_payloads(payload.get("members")),
        mode=_group_mode(payload.get("mode")),
        moderator_agent_id=_optional_text(payload.get("moderator_agent_id")),
        default_model=_optional_text(payload.get("default_model")),
        memory_scope=_memory_scope(payload.get("memory_scope")),
        tool_policy_id=_optional_text(payload.get("tool_policy_id")),
        enabled=bool(payload.get("enabled", True)),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )


def agent_group_member_from_payload(payload: Mapping[str, Any]) -> AgentGroupMemberSnapshot:
    return AgentGroupMemberSnapshot(
        agent_id=_text(payload.get("agent_id")),
        name=_text(payload.get("name") or payload.get("agent_name") or payload.get("agent_id")),
        role=_optional_text(payload.get("role")),
        sort_order=_int(payload.get("sort_order")),
        enabled=bool(payload.get("enabled", True)),
    )


def agent_group_members_from_payloads(payloads: Any) -> list[AgentGroupMemberSnapshot]:
    if not isinstance(payloads, list):
        return []
    return [agent_group_member_from_payload(item) for item in payloads if isinstance(item, Mapping)]


def group_run_snapshot_from_payload(
    payload: Mapping[str, Any] | GroupRunSnapshot,
) -> GroupRunSnapshot:
    if isinstance(payload, GroupRunSnapshot):
        return payload

    legacy_run_group_id = _optional_text(payload.get("run_group_id"))
    group_run_id = _text(payload.get("group_run_id") or legacy_run_group_id)
    group_id = _text(payload.get("group_id") or payload.get("agent_group_id"))
    runs_payload = payload.get("runs") or payload.get("child_runs") or []
    events = _RUN_PROJECTOR.events_from_payload(
        payload,
        run_id=group_run_id,
        keys=("events", "run_events", "recent_events", "timeline"),
    )
    return GroupRunSnapshot(
        group_run_id=group_run_id,
        run_group_id=legacy_run_group_id or group_run_id or None,
        group_id=group_id,
        title=_text(payload.get("title") or "Group run"),
        status=_text(payload.get("status") or "unknown"),
        objective=_text(payload.get("objective") or payload.get("user_goal")),
        participants=agent_group_members_from_payloads(payload.get("participants")),
        active_speaker_agent_id=_optional_text(payload.get("active_speaker_agent_id")),
        events=events,
        runs=[
            _RUN_PROJECTOR.timeline_snapshot_from_payload(item)
            for item in runs_payload
            if isinstance(item, Mapping)
        ],
        child_run_ids=[str(item) for item in payload.get("child_run_ids") or [] if str(item)],
        shared_artifacts=_RUN_PROJECTOR.artifacts_from_payload(
            {"artifacts": payload.get("shared_artifacts") or payload.get("artifacts")},
            run_id=group_run_id,
            events=events,
        ),
        pending_approvals=_RUN_PROJECTOR.approvals_from_payload(
            payload,
            run_id=group_run_id,
            group_run_id=group_run_id,
            keys=("pending_approvals", "pending_approval"),
            events=events,
        ),
        final_answer=_optional_text(payload.get("final_answer") or payload.get("summary")),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )


def _group_mode(value: Any) -> str:
    mode = _text(value) or "moderated"
    allowed = {"moderated", "round_robin", "debate", "pipeline", "parallel", "custom"}
    return mode if mode in allowed else "custom"


def _memory_scope(value: Any) -> str:
    scope = _text(value) or "shared"
    return scope if scope in {"shared", "per_agent", "hybrid"} else "shared"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
