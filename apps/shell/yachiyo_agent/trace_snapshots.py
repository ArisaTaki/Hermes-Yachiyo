"""Memory and Skill trace public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_run_event_payload, redact_secrets

from .contracts import MemoryTraceSnapshot, PublicRunEvent, SkillTraceSnapshot


def memory_trace_snapshots_from_events(events: list[PublicRunEvent]) -> list[MemoryTraceSnapshot]:
    traces: list[MemoryTraceSnapshot] = []
    for event in events:
        if _public_run_event_is_secret(event):
            continue
        trace = memory_trace_snapshot_from_event(event)
        if trace is not None:
            traces.append(trace)
    return traces


def skill_trace_snapshots_from_events(events: list[PublicRunEvent]) -> list[SkillTraceSnapshot]:
    traces: list[SkillTraceSnapshot] = []
    for event in events:
        if _public_run_event_is_secret(event):
            continue
        trace = skill_trace_snapshot_from_event(event)
        if trace is not None:
            traces.append(trace)
    return traces


def memory_trace_snapshot_from_event(event: PublicRunEvent) -> MemoryTraceSnapshot | None:
    if not event.event_type.startswith("memory."):
        return None
    payload = dict(event.payload)
    result = _nested_mapping(payload, "result")
    memories = _mapping_items(payload.get("memories")) or _mapping_items(result.get("memories"))
    first_memory = memories[0] if memories else {}
    action = _memory_trace_action(event.event_type)
    memory_id = _optional_text(
        result.get("memory_id")
        or payload.get("memory_id")
        or first_memory.get("memory_id")
    )
    memory_kind = _optional_text(
        result.get("kind")
        or payload.get("memory_kind")
        or first_memory.get("kind")
    )
    memory_scope = _optional_text(
        result.get("scope")
        or payload.get("scope")
        or first_memory.get("scope")
    )
    count = _optional_int(payload.get("count"))
    if count is None:
        count = len(memories)
    detail_parts = [
        _optional_text(result.get("action")) or action,
        memory_kind,
        memory_scope,
    ]
    return MemoryTraceSnapshot(
        trace_id=_trace_id(event),
        run_id=event.run_id,
        event_id=_optional_text(event.event_id),
        sequence=event.sequence,
        event_type=event.event_type,
        status=_trace_status(payload.get("status") or result.get("status")),
        action=action,
        memory_id=memory_id,
        memory_kind=memory_kind,
        memory_scope=memory_scope,
        count=count,
        title=_memory_trace_title(event.event_type, action),
        detail=" · ".join(part for part in detail_parts if part),
        payload_preview=_trace_payload_preview(payload),
        created_at=event.created_at,
        **_trace_context_kwargs(payload),
    )


def skill_trace_snapshot_from_event(event: PublicRunEvent) -> SkillTraceSnapshot | None:
    if not event.event_type.startswith("skill."):
        return None
    payload = dict(event.payload)
    result = _nested_mapping(payload, "result")
    skill = _nested_mapping(payload, "skill") or _nested_mapping(result, "skill")
    skill_id = _optional_text(result.get("skill_id") or skill.get("skill_id") or payload.get("skill_id"))
    skill_name = _optional_text(result.get("name") or skill.get("name") or payload.get("skill_name"))
    source_ref = _optional_text(result.get("source_ref") or skill.get("source_ref") or payload.get("source_ref"))
    source_type = _optional_text(
        result.get("source_type") or skill.get("source_type") or payload.get("source_type")
    )
    detail_parts = [
        _optional_text(result.get("description") or skill.get("description")),
        source_ref,
        source_type,
    ]
    return SkillTraceSnapshot(
        trace_id=_trace_id(event),
        run_id=event.run_id,
        event_id=_optional_text(event.event_id),
        sequence=event.sequence,
        event_type=event.event_type,
        status=_trace_status(payload.get("status") or result.get("status")),
        skill_id=skill_id,
        skill_name=skill_name,
        source_ref=source_ref,
        source_type=source_type,
        tool_name=_optional_text(payload.get("tool")),
        title=skill_name or _skill_trace_title(event.event_type),
        detail=" · ".join(part for part in detail_parts if part),
        payload_preview=_trace_payload_preview(payload),
        created_at=event.created_at,
        **_trace_context_kwargs(payload),
    )


def _trace_context_kwargs(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_run_id": _optional_text(payload.get("source_run_id")),
        "source_runnable_id": _optional_text(
            payload.get("source_runnable_id")
            or payload.get("source_agent_id")
            or payload.get("member_agent_id")
            or payload.get("agent_id")
        ),
        "source_runnable_name": _optional_text(
            payload.get("source_runnable_name")
            or payload.get("source_agent_name")
            or payload.get("member_agent_name")
            or payload.get("agent_name")
        ),
        "workflow_id": _optional_text(payload.get("workflow_id")),
        "workflow_run_id": _optional_text(payload.get("workflow_run_id")),
        "workflow_node_id": _optional_text(payload.get("workflow_node_id")),
        "workflow_node_label": _optional_text(payload.get("workflow_node_label")),
        "group_id": _optional_text(payload.get("group_id")),
        "group_run_id": _optional_text(payload.get("group_run_id") or payload.get("run_group_id")),
    }


def _trace_id(event: PublicRunEvent) -> str:
    return _text(event.event_id) or f"{event.run_id}:{event.event_type}:{event.sequence}"


def _memory_trace_action(event_type: str) -> str:
    if event_type == "memory.retrieved":
        return "retrieved"
    if event_type.startswith("memory.write."):
        return event_type.rsplit(".", 1)[-1]
    return event_type


def _memory_trace_title(event_type: str, action: str) -> str:
    titles = {
        "memory.retrieved": "Memory retrieved",
        "memory.write.add": "Memory added",
        "memory.write.replace": "Memory updated",
        "memory.write.remove": "Memory removed",
    }
    return titles.get(event_type, f"Memory {action}")


def _skill_trace_title(event_type: str) -> str:
    if event_type == "skill.selected":
        return "Skill selected"
    if event_type.startswith("skill.dispatch."):
        return "Skill dispatched"
    return event_type


def _trace_status(value: Any) -> str:
    status = _text(value)
    if status == "ok":
        return "completed"
    return status or "completed"


def _trace_payload_preview(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _mapping(payload)


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _nested_mapping(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    redacted = redact_run_event_payload(dict(value))
    result = dict(redacted) if isinstance(redacted, Mapping) else {}
    return _restore_configured_flags(value, result)


def _restore_configured_flags(source: Any, target: Any) -> dict[str, Any]:
    if not isinstance(source, Mapping) or not isinstance(target, Mapping):
        return dict(target) if isinstance(target, Mapping) else {}
    result = dict(target)
    for key, item in source.items():
        key_text = _text(key)
        target_item = result.get(key_text)
        if key_text.endswith("_configured") and isinstance(item, bool):
            result[key_text] = item
        elif isinstance(item, Mapping) and isinstance(target_item, Mapping):
            result[key_text] = _restore_configured_flags(item, target_item)
        elif isinstance(item, list) and isinstance(target_item, list):
            result[key_text] = [
                _restore_configured_flags(source_item, redacted_item)
                if isinstance(source_item, Mapping) and isinstance(redacted_item, Mapping)
                else redacted_item
                for source_item, redacted_item in zip(item, target_item, strict=False)
            ]
    return result


def _public_run_event_is_secret(event: PublicRunEvent) -> bool:
    return event.sensitivity == "secret"


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
