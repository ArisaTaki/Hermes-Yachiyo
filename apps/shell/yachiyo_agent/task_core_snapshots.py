"""Task core projection helpers for Chat and Agent Studio snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_json_value

from .contracts import PublicRunEvent, TaskCoreSnapshot


def task_core_snapshot_from_payload(
    payload: Mapping[str, Any],
    *,
    events: Iterable[PublicRunEvent] | None = None,
) -> TaskCoreSnapshot | None:
    """Project the DeepAgent-style task core from planner metadata or events."""
    for candidate in _task_core_candidates(payload, events or []):
        snapshot = _task_core_snapshot_from_candidate(candidate)
        if snapshot is not None:
            return snapshot
    return None


def _task_core_candidates(
    payload: Mapping[str, Any],
    events: Iterable[PublicRunEvent],
) -> Iterable[Any]:
    yield payload.get("task_core")
    yield payload.get("planner_task_core")

    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        yield metadata.get("yachiyo_task_core")
        yield metadata.get("task_core")

    yield _task_core_from_plan(payload.get("plan"))
    yield _task_core_from_plan(payload.get("runtime_plan"))

    planner_decision = payload.get("planner_decision")
    if isinstance(planner_decision, Mapping):
        yield _task_core_from_plan(planner_decision.get("plan"))

    for event_payload in _raw_public_event_payloads(payload):
        yield event_payload.get("task_core")
        yield _task_core_from_plan(event_payload.get("plan"))
        yield _task_core_from_plan(event_payload.get("runtime_plan"))

    for event in events:
        if event.visibility != "user" or event.sensitivity != "public":
            continue
        event_payload = event.payload
        yield event_payload.get("task_core")
        yield _task_core_from_plan(event_payload.get("plan"))
        yield _task_core_from_plan(event_payload.get("runtime_plan"))


def _task_core_from_plan(plan: Any) -> Any:
    if not isinstance(plan, Mapping):
        return None
    return plan.get("task_core")


def _raw_public_event_payloads(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for key in ("events", "run_events", "timeline"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, Mapping):
                continue
            if _raw_event_is_private(item):
                continue
            event_payload = item.get("payload")
            if isinstance(event_payload, Mapping):
                yield event_payload
            else:
                yield {
                    str(raw_key): raw_value
                    for raw_key, raw_value in item.items()
                    if raw_key
                    not in {
                        "event_id",
                        "run_id",
                        "sequence",
                        "schema_version",
                        "event_type",
                        "event",
                        "title",
                        "detail",
                        "actor",
                        "visibility",
                        "sensitivity",
                        "created_at",
                    }
                }


def _raw_event_is_private(event: Mapping[str, Any]) -> bool:
    return (
        str(event.get("visibility") or "").strip() == "internal"
        or str(event.get("sensitivity") or "").strip() == "secret"
    )


def _task_core_snapshot_from_candidate(candidate: Any) -> TaskCoreSnapshot | None:
    if isinstance(candidate, TaskCoreSnapshot):
        return candidate
    if not isinstance(candidate, Mapping):
        return None
    redacted = redact_json_value(dict(candidate))
    if not isinstance(redacted, Mapping):
        return None
    try:
        return TaskCoreSnapshot.model_validate(redacted)
    except ValueError:
        return None
