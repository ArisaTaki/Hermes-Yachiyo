"""Agent group and group run public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

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


def group_run_participants_from_payload(
    payload: Mapping[str, Any],
) -> list[AgentGroupMemberSnapshot]:
    participants = agent_group_members_from_payloads(payload.get("participants"))
    return participants or agent_group_members_from_payloads(payload.get("members"))


def group_run_snapshot_from_payload(
    payload: Mapping[str, Any] | GroupRunSnapshot,
) -> GroupRunSnapshot:
    if isinstance(payload, GroupRunSnapshot):
        return payload

    legacy_run_group_id = _optional_text(payload.get("run_group_id"))
    group_run_id = _text(payload.get("group_run_id") or legacy_run_group_id)
    group_id = _text(payload.get("group_id") or payload.get("agent_group_id"))
    runs_payload = payload.get("runs") or payload.get("child_runs") or []
    child_run_ids = [_text(item) for item in payload.get("child_run_ids") or [] if _text(item)]
    participants = group_run_participants_from_payload(payload)
    events = _RUN_PROJECTOR.events_from_payload(
        {
            "events": _group_run_events_with_lifecycle(
                payload,
                group_run_id=group_run_id,
                group_id=group_id,
                objective=_text(payload.get("objective") or payload.get("user_goal")),
                child_run_ids=child_run_ids,
            )
        },
        run_id=group_run_id,
        keys=("events",),
    )
    return GroupRunSnapshot(
        group_run_id=group_run_id,
        run_group_id=legacy_run_group_id or group_run_id or None,
        group_id=group_id,
        title=_text(payload.get("title") or "Group run"),
        status=_text(payload.get("status") or "unknown"),
        objective=_text(payload.get("objective") or payload.get("user_goal")),
        participants=participants,
        active_speaker_agent_id=_optional_text(payload.get("active_speaker_agent_id")),
        events=events,
        runs=[
            _RUN_PROJECTOR.timeline_snapshot_from_payload(
                _group_run_child_payload(
                    item,
                    group_run_id=group_run_id,
                    group_id=group_id,
                )
            )
            for item in runs_payload
            if isinstance(item, Mapping)
        ],
        child_run_ids=child_run_ids,
        shared_artifacts=_RUN_PROJECTOR.artifacts_from_payload(
            {"artifacts": payload.get("shared_artifacts") or payload.get("artifacts")},
            run_id=group_run_id,
            events=events,
        ),
        pending_approvals=[
            approval
            for approval in _RUN_PROJECTOR.approvals_from_payload(
                payload,
                run_id=group_run_id,
                group_run_id=group_run_id,
                keys=("pending_approvals", "pending_approval"),
                events=events,
            )
            if approval.status == "pending"
        ],
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


def _group_run_events_with_lifecycle(
    payload: Mapping[str, Any],
    *,
    group_run_id: str,
    group_id: str,
    objective: str,
    child_run_ids: list[str],
) -> list[dict[str, Any]]:
    raw_events = _raw_events_from_payload(
        payload,
        ("events", "run_events", "recent_events", "timeline"),
    )
    if not group_run_id:
        return raw_events
    raw_events = _group_run_stream_events(
        raw_events,
        group_run_id=group_run_id,
        group_id=group_id,
    )

    existing_types = {_event_type(event) for event in raw_events}
    lifecycle_context = _group_run_lifecycle_context(
        payload,
        group_run_id=group_run_id,
        group_id=group_id,
        objective=objective,
        child_run_ids=child_run_ids,
    )
    events: list[dict[str, Any]] = []
    if "group.run.started" not in existing_types:
        events.append(
            _group_run_lifecycle_event(
                "group.run.started",
                payload,
                lifecycle_context,
                created_at=_text(payload.get("created_at")),
            )
        )
    events.extend(raw_events)

    terminal_event_type = _group_run_terminal_event_type(payload.get("status"))
    if terminal_event_type and terminal_event_type not in existing_types:
        events.append(
            _group_run_lifecycle_event(
                terminal_event_type,
                payload,
                {**lifecycle_context, "status": _text(payload.get("status"))},
                created_at=_text(payload.get("updated_at") or payload.get("created_at")),
            )
        )
    return events


def _group_run_stream_events(
    events: list[dict[str, Any]],
    *,
    group_run_id: str,
    group_id: str,
) -> list[dict[str, Any]]:
    return [
        _group_run_stream_event(
            event,
            group_run_id=group_run_id,
            group_id=group_id,
        )
        for event in events
    ]


def _group_run_stream_event(
    event: dict[str, Any],
    *,
    group_run_id: str,
    group_id: str,
) -> dict[str, Any]:
    item = dict(event)
    payload = dict(item.get("payload")) if isinstance(item.get("payload"), Mapping) else {}
    payload.setdefault("group_run_id", group_run_id)
    if group_id:
        payload.setdefault("group_id", group_id)
    item["payload"] = payload

    event_run_id = _text(item.get("run_id"))
    if not event_run_id or event_run_id == group_run_id or "sequence" not in item:
        return item

    source_sequence = item.pop("sequence")
    payload.setdefault("source_run_id", event_run_id)
    payload.setdefault("source_sequence", source_sequence)
    item["payload"] = payload
    return item


def _group_run_child_payload(
    payload: Mapping[str, Any],
    *,
    group_run_id: str,
    group_id: str,
) -> dict[str, Any]:
    child = dict(payload)
    if group_run_id:
        child.setdefault("group_run_id", group_run_id)
        child.setdefault("run_group_id", group_run_id)
    if group_id:
        child.setdefault("group_id", group_id)
    for key in ("events", "run_events", "recent_events", "timeline"):
        value = child.get(key)
        if isinstance(value, list):
            child[key] = [
                _group_run_child_event_context(
                    item,
                    group_run_id=group_run_id,
                    group_id=group_id,
                )
                for item in value
                if isinstance(item, Mapping)
            ]
    return child


def _group_run_child_event_context(
    event: Mapping[str, Any],
    *,
    group_run_id: str,
    group_id: str,
) -> dict[str, Any]:
    item = dict(event)
    payload = dict(item.get("payload")) if isinstance(item.get("payload"), Mapping) else {}
    timeline_payload = {
        key: item.get(key)
        for key in (
            "input_preview",
            "input",
            "output_preview",
            "result",
            "pending_approval",
            "approval",
            "artifact",
        )
        if key in item
    }
    payload = {**timeline_payload, **payload}
    if group_run_id:
        payload.setdefault("group_run_id", group_run_id)
        payload.setdefault("run_group_id", group_run_id)
    if group_id:
        payload.setdefault("group_id", group_id)
    if payload:
        item["payload"] = payload
    return item


def _raw_events_from_payload(
    payload: Mapping[str, Any],
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if value and isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _event_type(event: Mapping[str, Any]) -> str:
    return _text(event.get("event_type") or event.get("event"))


def _group_run_lifecycle_context(
    payload: Mapping[str, Any],
    *,
    group_run_id: str,
    group_id: str,
    objective: str,
    child_run_ids: list[str],
) -> dict[str, Any]:
    return {
        "group_run_id": group_run_id,
        "run_group_id": _text(payload.get("run_group_id") or group_run_id),
        "group_id": group_id,
        "objective": objective,
        "status": _text(payload.get("status") or "unknown"),
        "child_run_ids": child_run_ids,
        "participant_count": len(group_run_participants_from_payload(payload)),
    }


def _group_run_lifecycle_event(
    event_type: str,
    payload: Mapping[str, Any],
    lifecycle_context: dict[str, Any],
    *,
    created_at: str = "",
) -> dict[str, Any]:
    label = _text(payload.get("title") or payload.get("objective") or "Group run")
    event = {
        "event_type": event_type,
        "detail": label,
        "payload": dict(lifecycle_context),
    }
    if created_at:
        event["created_at"] = created_at
    return event


def _group_run_terminal_event_type(value: Any) -> str:
    status = _text(value)
    if status == "completed":
        return "group.run.completed"
    if status == "failed":
        return "group.run.failed"
    if status == "cancelled":
        return "group.run.cancelled"
    return ""


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
