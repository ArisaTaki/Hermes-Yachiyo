"""RunTimeline metadata public snapshot helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_run_event_payload, redact_secrets

from .contracts import PlannerTraceSummarySnapshot, PublicRunEvent, RunTimelineChildSnapshot

_PLANNER_INTENT_EVENTS = {"agent.intent.selected", "group.run.intent.selected"}
_PLANNER_CREATED_EVENTS = {"agent.plan.created", "group.run.plan.created"}
_PLANNER_STEP_EVENTS = {"agent.plan.step", "group.run.plan.step"}
_PLANNER_SELECTION_EVENTS = {"agent.plan.selection", "group.run.plan.selection"}


def timeline_child_snapshots_from_payloads(payloads: Any) -> list[RunTimelineChildSnapshot]:
    if not isinstance(payloads, list):
        return []
    children: list[RunTimelineChildSnapshot] = []
    for item in payloads:
        if isinstance(item, Mapping):
            children.append(timeline_child_snapshot_from_payload(item))
        else:
            children.append(RunTimelineChildSnapshot(run_id=_text(item)))
    return children


def timeline_child_snapshots_from_events(
    events: list[PublicRunEvent],
) -> list[RunTimelineChildSnapshot]:
    children: list[RunTimelineChildSnapshot] = []
    for event in events:
        child = timeline_child_snapshot_from_event(event)
        if child is not None:
            children.append(child)
    return _unique_children(children)


def timeline_child_snapshot_from_payload(payload: Mapping[str, Any]) -> RunTimelineChildSnapshot:
    kind = _optional_text(payload.get("kind"))
    runnable_id = _optional_text(payload.get("runnable_id"))
    return RunTimelineChildSnapshot(
        run_id=_text(payload.get("run_id")),
        title=_optional_text(payload.get("title") or payload.get("user_goal")),
        status=_text(payload.get("status")),
        kind=kind,
        parent_run_id=_optional_text(payload.get("parent_run_id")),
        group_run_id=_optional_text(payload.get("group_run_id") or payload.get("run_group_id")),
        run_group_id=_optional_text(payload.get("run_group_id") or payload.get("group_run_id")),
        workflow_run_id=_optional_text(payload.get("workflow_run_id")),
        workflow_node_id=_optional_text(payload.get("workflow_node_id")),
        workflow_node_label=_optional_text(payload.get("workflow_node_label")),
        agent_id=_optional_text(
            payload.get("agent_id")
            or payload.get("member_agent_id")
            or (runnable_id if kind == "agent_run" else "")
        ),
        workflow_id=_optional_text(
            payload.get("workflow_id")
            or (runnable_id if kind == "workflow_run" else "")
        ),
        planner_summary=planner_trace_summary_from_payload(payload),
    )


def timeline_child_snapshot_from_event(event: PublicRunEvent) -> RunTimelineChildSnapshot | None:
    payload = event.payload
    child_run_id = _text(payload.get("child_run_id") or payload.get("child_agent_run_id"))
    if not child_run_id:
        return None
    return timeline_child_snapshot_from_payload({
        "run_id": child_run_id,
        "title": payload.get("child_run_title") or payload.get("workflow_node_label"),
        "status": payload.get("child_run_status") or payload.get("status"),
        "kind": payload.get("child_run_kind") or payload.get("child_kind") or "agent_run",
        "parent_run_id": event.run_id,
        "group_run_id": payload.get("group_run_id") or payload.get("run_group_id"),
        "run_group_id": payload.get("run_group_id") or payload.get("group_run_id"),
        "workflow_run_id": payload.get("workflow_run_id") or event.run_id,
        "workflow_node_id": payload.get("workflow_node_id"),
        "workflow_node_label": payload.get("workflow_node_label"),
        "agent_id": (
            payload.get("agent_id")
            or payload.get("member_agent_id")
            or payload.get("source_runnable_id")
        ),
        "workflow_id": payload.get("child_workflow_id") or payload.get("workflow_id"),
    })


def merge_timeline_child_snapshots(
    explicit_children: list[RunTimelineChildSnapshot],
    event_children: list[RunTimelineChildSnapshot],
) -> list[RunTimelineChildSnapshot]:
    return _unique_children([*explicit_children, *event_children])


def planner_trace_summary_from_payload(
    payload: Mapping[str, Any],
) -> PlannerTraceSummarySnapshot | None:
    explicit = payload.get("planner_summary")
    if isinstance(explicit, PlannerTraceSummarySnapshot):
        return explicit
    if isinstance(explicit, Mapping):
        try:
            return PlannerTraceSummarySnapshot.model_validate(explicit)
        except ValueError:
            pass

    events = _event_items_from_payload(payload)
    if not events:
        return None

    source = ""
    decision_id = None
    plan_id = None
    intent_kind = None
    intent_title = None
    route_to_studio = None
    selection_source = None
    selection_role = None
    selection_reason = None
    planner_entrypoint = None
    entrypoint_source = None
    launcher_mode = None
    launcher_surface = None
    runnable_kind = None
    followup_target: dict[str, Any] = {}
    plan_tools: list[str] = []
    selected_tools: list[str] = []
    plan_capabilities: list[str] = []
    required_capabilities: list[str] = []
    missing_capabilities: list[str] = []
    approvals_required: list[str] = []
    artifacts_expected: list[str] = []
    open_questions: list[str] = []
    step_ids: set[str] = set()
    step_count = 0
    event_count = 0

    for event in events:
        event_type = _event_type(event)
        payload_record = _event_payload(event)
        if not event_type or _event_is_secret(event, payload_record):
            continue
        is_desktop_planner_event = (
            event_type == "agent.desktop.intent_planned"
            and _runtime_planner_desktop_event(payload_record)
        )
        if (
            event_type not in _PLANNER_INTENT_EVENTS
            and event_type not in _PLANNER_CREATED_EVENTS
            and event_type not in _PLANNER_STEP_EVENTS
            and event_type not in _PLANNER_SELECTION_EVENTS
            and not is_desktop_planner_event
        ):
            continue

        event_count += 1
        source = source or _text(payload_record.get("source") or event.get("source"))
        decision_id = decision_id or _optional_text(payload_record.get("decision_id"))
        plan_id = plan_id or _optional_text(payload_record.get("plan_id"))
        route_to_studio = _optional_bool(payload_record.get("route_to_studio"), route_to_studio)

        if event_type in _PLANNER_INTENT_EVENTS:
            intent = _mapping(payload_record.get("intent"))
            intent_kind = intent_kind or _optional_text(intent.get("kind"))
            intent_title = intent_title or _optional_text(intent.get("title"))
            _add_strings(required_capabilities, intent.get("required_capabilities"))
            continue

        if event_type in _PLANNER_CREATED_EVENTS:
            plan = _mapping(payload_record.get("plan"))
            plan_id = plan_id or _optional_text(plan.get("plan_id"))
            route_to_studio = _optional_bool(plan.get("route_to_studio"), route_to_studio)
            intent = _mapping(plan.get("intent"))
            intent_kind = intent_kind or _optional_text(intent.get("kind"))
            intent_title = intent_title or _optional_text(intent.get("title"))
            _add_strings(required_capabilities, intent.get("required_capabilities"))
            for capability in _mapping_list(plan.get("capabilities")):
                _add_string(plan_capabilities, capability.get("capability_id"))
            tool_plan = _mapping(plan.get("tool_plan"))
            _add_strings(required_capabilities, tool_plan.get("required_capabilities"))
            _add_strings(missing_capabilities, tool_plan.get("missing_capabilities"))
            _add_strings(approvals_required, tool_plan.get("approvals_required"))
            _add_strings(artifacts_expected, tool_plan.get("artifacts_expected"))
            _add_strings(open_questions, tool_plan.get("open_questions"))
            step_count = max(
                step_count,
                _add_plan_steps(
                    tool_plan.get("steps"),
                    step_ids=step_ids,
                    plan_tools=plan_tools,
                    plan_capabilities=plan_capabilities,
                    approvals_required=approvals_required,
                ),
            )
            continue

        if event_type in _PLANNER_STEP_EVENTS:
            step_count = max(
                step_count,
                _add_plan_steps(
                    [payload_record.get("step")],
                    step_ids=step_ids,
                    plan_tools=plan_tools,
                    plan_capabilities=plan_capabilities,
                    approvals_required=approvals_required,
                ),
            )
            continue

        if event_type in _PLANNER_SELECTION_EVENTS:
            selection_source = selection_source or _optional_text(payload_record.get("selection_source"))
            selection_role = selection_role or _optional_text(payload_record.get("selection_role"))
            selection_reason = selection_reason or _optional_text(payload_record.get("selection_reason"))
            planner_entrypoint = planner_entrypoint or _optional_text(payload_record.get("planner_entrypoint"))
            entrypoint_source = entrypoint_source or _optional_text(payload_record.get("entrypoint_source"))
            launcher_mode = launcher_mode or _optional_text(payload_record.get("launcher_mode"))
            launcher_surface = launcher_surface or _optional_text(payload_record.get("launcher_surface"))
            runnable_kind = runnable_kind or _optional_text(payload_record.get("runnable_kind"))
            followup_target = followup_target or _public_mapping(payload_record.get("followup_target"))
            _add_strings(plan_tools, payload_record.get("plan_tools"))
            _add_strings(selected_tools, payload_record.get("selected_tools"))
            _add_strings(plan_capabilities, payload_record.get("plan_capabilities"))
            _add_strings(required_capabilities, payload_record.get("required_capabilities"))
            _add_strings(missing_capabilities, payload_record.get("missing_capabilities"))
            _add_strings(approvals_required, payload_record.get("approvals_required"))
            _add_strings(artifacts_expected, payload_record.get("artifacts_expected"))
            _add_strings(open_questions, payload_record.get("open_questions"))
            step_count = max(step_count, _optional_int(payload_record.get("plan_step_count")) or 0)
            continue

        tool_name = _optional_text(payload_record.get("tool"))
        if tool_name:
            _add_string(plan_tools, tool_name)
            _add_string(selected_tools, tool_name)
        selection_reason = selection_reason or _optional_text(
            payload_record.get("planning_reason") or payload_record.get("reason")
        )
        if payload_record.get("approval_required"):
            _add_string(approvals_required, tool_name or selection_reason)
        step_count = max(step_count + 1, len(step_ids) + 1)

    if not event_count:
        return None
    return PlannerTraceSummarySnapshot(
        source=source,
        decision_id=decision_id,
        plan_id=plan_id,
        intent_kind=intent_kind,
        intent_title=intent_title,
        route_to_studio=route_to_studio,
        selection_source=selection_source,
        selection_role=selection_role,
        selection_reason=selection_reason,
        planner_entrypoint=planner_entrypoint,
        entrypoint_source=entrypoint_source,
        launcher_mode=launcher_mode,
        launcher_surface=launcher_surface,
        runnable_kind=runnable_kind,
        followup_target=followup_target,
        plan_tools=plan_tools,
        selected_tools=selected_tools,
        plan_capabilities=plan_capabilities,
        required_capabilities=required_capabilities,
        missing_capabilities=missing_capabilities,
        approvals_required=approvals_required,
        artifacts_expected=artifacts_expected,
        open_questions=open_questions,
        step_count=max(step_count, len(step_ids)),
        event_count=event_count,
    )


def _unique_children(children: list[RunTimelineChildSnapshot]) -> list[RunTimelineChildSnapshot]:
    seen: set[str] = set()
    unique: list[RunTimelineChildSnapshot] = []
    for child in children:
        key = _text(child.run_id)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(child)
    return unique


def _event_items_from_payload(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("events", "run_events", "timeline"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        return [
            item.model_dump(mode="json") if isinstance(item, PublicRunEvent) else item
            for item in value
            if isinstance(item, (Mapping, PublicRunEvent))
        ]
    return []


def _event_type(event: Mapping[str, Any]) -> str:
    return _text(event.get("event_type") or event.get("event"))


def _event_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        return {**dict(event), **dict(payload)}
    return dict(event)


def _event_is_secret(event: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    return _text(event.get("sensitivity") or payload.get("sensitivity")) == "secret"


def _runtime_planner_desktop_event(payload: Mapping[str, Any]) -> bool:
    source = _text(payload.get("source"))
    planning_reason = _text(payload.get("planning_reason"))
    return source == "runtime_planner" or planning_reason.startswith("planner_")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _public_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    redacted = redact_run_event_payload(dict(value))
    return dict(redacted) if isinstance(redacted, Mapping) else {}


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _add_plan_steps(
    value: Any,
    *,
    step_ids: set[str],
    plan_tools: list[str],
    plan_capabilities: list[str],
    approvals_required: list[str],
) -> int:
    steps = _mapping_list(value)
    for index, step in enumerate(steps, start=1):
        step_id = _optional_text(step.get("step_id")) or f"step-{index}"
        step_ids.add(step_id)
        _add_string(plan_tools, step.get("tool_name"))
        _add_string(plan_capabilities, step.get("capability_id"))
        if step.get("approval_required"):
            _add_string(approvals_required, step_id)
    return len(step_ids)


def _add_strings(target: list[str], value: Any) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        _add_string(target, item)


def _add_string(target: list[str], value: Any) -> None:
    text = _text(value)
    if text and text not in target:
        target.append(text)


def _optional_bool(value: Any, fallback: bool | None = None) -> bool | None:
    if isinstance(value, bool):
        return value
    return fallback


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def run_timeline_rerun_provenance_from_payload(
    payload: Mapping[str, Any],
    events: list[PublicRunEvent],
) -> dict[str, str | None]:
    keys = (
        "rerun_of_run_id",
        "rerun_of_kind",
        "rerun_of_status",
        "rerun_of_runnable_id",
        "rerun_of_runnable_name",
    )
    direct = {key: _optional_text(payload.get(key)) for key in keys}
    direct["rerun_original_created_at"] = _optional_text(
        payload.get("rerun_original_created_at") or payload.get("original_created_at")
    )
    direct["rerun_original_updated_at"] = _optional_text(
        payload.get("rerun_original_updated_at") or payload.get("original_updated_at")
    )
    if direct.get("rerun_of_run_id"):
        return direct
    event = next((item for item in events if item.event_type == "run.rerun.started"), None)
    if event is None:
        return direct
    source = event.payload
    return {
        **{key: _optional_text(source.get(key)) for key in keys},
        "rerun_original_created_at": _optional_text(source.get("original_created_at")),
        "rerun_original_updated_at": _optional_text(source.get("original_updated_at")),
    }


def run_timeline_agent_id_from_payload(payload: Mapping[str, Any]) -> str:
    if _text(payload.get("kind")) == "agent_run":
        return _text(payload.get("runnable_id"))
    return ""


def workflow_run_id_from_payload(payload: Mapping[str, Any], run_id: str) -> str | None:
    explicit = _optional_text(payload.get("workflow_run_id"))
    if explicit:
        return explicit
    if _text(payload.get("kind")) == "workflow_run":
        return run_id or None
    return None


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
