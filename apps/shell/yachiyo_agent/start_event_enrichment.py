"""Shared start-payload planner event enrichment."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from .contracts import PlannerDecisionSnapshot
from .planner_projection import planner_run_event_payloads
from .runtime_execution import runtime_execution_envelope_payload_with_request_context


class StartPayloadPlanner(Protocol):
    def __call__(
        self,
        prompt: str,
        *,
        allowed_tools: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> PlannerDecisionSnapshot: ...


def start_payload_with_planner_events(
    raw_payload: Mapping[str, Any],
    request_payload: Mapping[str, Any],
    *,
    plan_task: StartPayloadPlanner,
    metadata_source: str,
) -> dict[str, Any]:
    payload = _payload_with_request_metadata(raw_payload, request_payload)
    if _payload_has_planner_events(payload):
        return payload

    prompt = _start_prompt(request_payload, payload)
    if not prompt:
        return payload

    decision = plan_task(
        prompt,
        allowed_tools=_optional_string_list(request_payload.get("allowed_tools")),
        metadata=_start_metadata(request_payload, source=metadata_source),
    )
    planner_events = _planner_public_events_for_start_payload(
        decision,
        run_id=_started_run_id(payload),
        after_sequence=_max_event_sequence(payload),
    )
    if not planner_events:
        return payload

    key = _event_list_key(payload)
    payload[key] = [*list(payload.get(key) or []), *planner_events]
    return payload


def start_payload_with_planner_decision_events(
    raw_payload: Mapping[str, Any],
    decision: PlannerDecisionSnapshot | None,
    *,
    event_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(raw_payload)
    if decision is None or _payload_has_planner_events(payload):
        return payload

    planner_events = _planner_public_events_for_start_payload(
        decision,
        run_id=_started_run_id(payload),
        after_sequence=_max_event_sequence(payload),
        event_context=event_context,
    )
    if not planner_events:
        return payload

    key = _event_list_key(payload)
    payload[key] = [*list(payload.get(key) or []), *planner_events]
    return payload


def _optional_string_list(value: Any) -> list[str] | None:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return None
    values = [str(item or "").strip() for item in value if str(item or "").strip()]
    return values or None


def _start_prompt(
    request_payload: Mapping[str, Any],
    response_payload: Mapping[str, Any],
) -> str:
    return str(
        request_payload.get("prompt")
        or request_payload.get("objective")
        or request_payload.get("goal")
        or response_payload.get("prompt")
        or response_payload.get("objective")
        or response_payload.get("user_goal")
        or request_payload.get("title")
        or response_payload.get("title")
        or ""
    ).strip()


def _start_metadata(request_payload: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    metadata = (
        dict(request_payload.get("metadata"))
        if isinstance(request_payload.get("metadata"), Mapping)
        else {}
    )
    metadata.setdefault("source", source)
    metadata["runtime_planner_entrypoint"] = True
    return metadata


def _payload_with_request_metadata(
    raw_payload: Mapping[str, Any],
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(raw_payload)
    request_metadata = (
        dict(request_payload.get("metadata"))
        if isinstance(request_payload.get("metadata"), Mapping)
        else {}
    )
    if not request_metadata:
        return payload
    response_metadata = (
        dict(payload.get("metadata")) if isinstance(payload.get("metadata"), Mapping) else {}
    )
    payload["metadata"] = {**request_metadata, **response_metadata}
    return payload


def _planner_public_events_for_start_payload(
    decision: PlannerDecisionSnapshot,
    *,
    run_id: str,
    after_sequence: int,
    event_context: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    sequence = after_sequence + 1
    for event_type, payload in planner_run_event_payloads(decision):
        event = {
            "event_type": event_type,
            "sequence": sequence,
            "payload": _planner_payload_with_event_context(payload, event_context),
        }
        if run_id:
            event["run_id"] = run_id
        events.append(event)
        sequence += 1
    return events


def _planner_payload_with_event_context(
    payload: Mapping[str, Any],
    context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    enriched = dict(payload)
    if not isinstance(context, Mapping):
        return enriched

    for key, value in context.items():
        if key == "runtime_execution_envelope":
            continue
        if value not in ("", None) and key not in enriched:
            enriched[key] = value

    envelope = payload.get("runtime_execution_envelope")
    if isinstance(envelope, Mapping):
        enriched["runtime_execution_envelope"] = (
            runtime_execution_envelope_payload_with_request_context(envelope, context)
        )
    return enriched


def _payload_has_planner_events(payload: Mapping[str, Any]) -> bool:
    for event in _raw_start_events(payload):
        event_type = str(event.get("event_type") or event.get("event") or "").strip()
        event_payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        planner_type = str(event_payload.get("planner_event_type") or "").strip()
        if event_type in _PLANNER_EVENT_TYPES or planner_type in _PLANNER_EVENT_TYPES:
            return True
    return False


def _raw_start_events(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("events", "run_events", "recent_events", "timeline"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _event_list_key(payload: Mapping[str, Any]) -> str:
    for key in ("events", "run_events", "recent_events", "timeline"):
        if isinstance(payload.get(key), list):
            return key
    return "events"


def _max_event_sequence(payload: Mapping[str, Any]) -> int:
    sequence = 0
    for event in _raw_start_events(payload):
        try:
            sequence = max(sequence, int(event.get("sequence") or 0))
        except (TypeError, ValueError):
            continue
    return sequence


def _started_run_id(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("run_id")
        or payload.get("workflow_run_id")
        or payload.get("agent_run_id")
        or payload.get("group_run_id")
        or payload.get("run_group_id")
        or payload.get("task_id")
        or ""
    ).strip()


_PLANNER_EVENT_TYPES = {
    "agent.intent.selected",
    "agent.plan.created",
    "agent.task_core.created",
    "agent.plan.step",
    "agent.plan.selection",
    "agent.replan.requested",
    "agent.replan.recovery.updated",
    "agent.task.workspace_item.updated",
    "agent.task.todo.updated",
    "agent.task.checkpoint.updated",
    "group.run.intent.selected",
    "group.run.plan.created",
    "group.run.task_core.created",
    "group.run.plan.step",
    "group.run.plan.selection",
    "group.run.replan.requested",
    "group.run.replan.recovery.updated",
    "group.run.task.workspace_item.updated",
    "group.run.task.todo.updated",
    "group.run.task.checkpoint.updated",
    "workflow.run.intent.selected",
    "workflow.run.plan.created",
    "workflow.run.task_core.created",
    "workflow.run.plan.step",
    "workflow.run.plan.selection",
    "workflow.run.replan.requested",
    "workflow.run.replan.recovery.updated",
    "workflow.run.task.workspace_item.updated",
    "workflow.run.task.todo.updated",
    "workflow.run.task.checkpoint.updated",
    "workflow.task.workspace_item.updated",
    "workflow.task.todo.updated",
    "workflow.task.checkpoint.updated",
}
