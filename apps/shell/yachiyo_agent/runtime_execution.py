"""Runtime execution envelopes derived from planner decisions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import (
    PlannerDecisionSnapshot,
    RuntimeExecutionEnvelopeSnapshot,
    RuntimeExecutionRequestSnapshot,
    ToolPlanStepSnapshot,
)
from .planner_execution import (
    planner_full_plan_execution_tool_requests,
    planner_tool_requests_for_decision,
)
from .task_progress_snapshots import task_progress_summary_from_task_core


def runtime_execution_envelope_from_decision(
    decision: PlannerDecisionSnapshot | None,
    *,
    allowed_tools: Iterable[str] | None = None,
    direct: bool = False,
    full_plan: bool = False,
) -> RuntimeExecutionEnvelopeSnapshot | None:
    if decision is None:
        return None
    clean_allowed = _allowed_tools(decision, allowed_tools)
    request_payloads = (
        planner_full_plan_execution_tool_requests(
            _full_plan_tool_requests_from_decision(decision, clean_allowed),
            clean_allowed,
        )
        if full_plan and _supports_full_plan_projection(decision)
        else planner_tool_requests_for_decision(
            decision,
            clean_allowed,
            direct=direct,
            execution_normalized=True,
        )
    )
    steps = _steps_by_id(decision)
    requests: list[RuntimeExecutionRequestSnapshot] = []
    for index, request in enumerate(request_payloads, start=1):
        requests.append(
            _execution_request_snapshot(
                request,
                index=index,
                decision=decision,
                steps=steps,
                previous_requests=requests,
            )
        )
    tool_plan = decision.plan.tool_plan
    runtime_metadata = _execution_envelope_runtime_metadata(requests, decision)
    return RuntimeExecutionEnvelopeSnapshot(
        envelope_id=f"execution-envelope-{decision.plan.plan_id}",
        decision_id=decision.decision_id,
        plan_id=decision.plan.plan_id,
        intent_kind=str(decision.selected_intent.kind or ""),
        requests=requests,
        task_core=decision.plan.task_core,
        task_progress=task_progress_summary_from_task_core(decision.plan.task_core),
        approvals_required=list(tool_plan.approvals_required),
        artifacts_expected=list(tool_plan.artifacts_expected),
        open_questions=list(tool_plan.open_questions),
        route_to_studio=bool(decision.plan.route_to_studio),
        runtime_doctrine=runtime_metadata["runtime_doctrine"],
        runtime_stage_counts=runtime_metadata["runtime_stage_counts"],
        replan_signal_count=runtime_metadata["replan_signal_count"],
    )


def runtime_execution_envelope_payload(
    decision: PlannerDecisionSnapshot | None,
    *,
    allowed_tools: Iterable[str] | None = None,
    direct: bool = False,
    full_plan: bool = False,
) -> dict[str, Any]:
    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
        direct=direct,
        full_plan=full_plan,
    )
    if envelope is None:
        return {}
    return envelope.model_dump(mode="json")


def runtime_execution_envelope_payload_with_request_context(
    envelope: Mapping[str, Any],
    context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(envelope)
    request_context = _execution_request_context(context)
    if not request_context:
        return payload

    requests = payload.get("requests")
    if isinstance(requests, list):
        payload["requests"] = [
            _execution_request_with_context(request, request_context)
            if isinstance(request, Mapping)
            else request
            for request in requests
        ]
    return payload


def _supports_full_plan_projection(decision: PlannerDecisionSnapshot) -> bool:
    return str(decision.selected_intent.kind or "").strip() in {
        "clipboard_operation",
        "code_task",
        "communication",
        "data_analysis",
        "desktop_operation",
        "file_access",
        "file_operation",
        "file_organization",
        "information_capture",
        "media_playback",
        "multi_agent",
        "report_generation",
        "schedule",
        "system_control",
        "web_research",
        "workflow_orchestration",
    }


def _full_plan_tool_requests_from_decision(
    decision: PlannerDecisionSnapshot,
    allowed_tools: set[str],
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for step in list(decision.plan.tool_plan.steps or []):
        tool_name = _text(getattr(step, "tool_name", None))
        if not tool_name or tool_name not in allowed_tools:
            continue
        status = _text(getattr(step, "status", None)) or "planned"
        if status in {"unavailable", "skipped"}:
            continue
        input_preview = getattr(step, "input_preview", None)
        request_input = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        step_id = _text(getattr(step, "step_id", None))
        capability_id = _text(getattr(step, "capability_id", None))
        request: dict[str, Any] = {
            "protocol": "json_fallback",
            "tool": tool_name,
            "input": request_input,
            "source": "runtime_planner",
            "planning_reason": f"planner_full_plan_{decision.selected_intent.kind}",
            "approval_required": bool(getattr(step, "approval_required", False)),
            "status": status,
        }
        if step_id:
            request["step_id"] = step_id
            request["planner_step_id"] = step_id
        if capability_id:
            request["capability_id"] = capability_id
        if _request_needs_model_materialization(tool_name, request_input):
            request["continue_to_model"] = True
        requests.append(request)
    return requests


def _request_needs_model_materialization(
    tool_name: str,
    request_input: Mapping[str, Any],
) -> bool:
    if tool_name == "notes.create":
        return bool(request_input.get("body_source")) and not str(
            request_input.get("body") or ""
        ).strip()
    if tool_name == "artifact.write":
        if str(request_input.get("content") or "").strip():
            return False
        return bool(
            request_input.get("body_source")
            or request_input.get("path")
            or request_input.get("paths")
        )
    if tool_name in {
        "app.focus_and_safe_type_text",
        "app.focus_and_type_into_ui_element",
        "app.open_and_safe_type_text",
        "app.open_and_type_into_ui_element",
        "desktop.safe_type_text",
        "desktop.type",
        "desktop.type_into_ui_element",
        "desktop.type_text",
    }:
        return bool(request_input.get("body_source")) and not str(
            request_input.get("text") or ""
        ).strip()
    return False


_EXECUTION_REQUEST_CONTEXT_KEYS = {
    "workspace_id",
    "group_run_id",
    "run_group_id",
    "group_id",
    "workflow_run_id",
    "workflow_id",
    "workflow_node_id",
    "workflow_node_label",
    "workflow_node_kind",
}


def _execution_request_context(context: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(context, Mapping):
        return {}
    return {
        key: text
        for key in _EXECUTION_REQUEST_CONTEXT_KEYS
        if (text := _text(context.get(key)))
    }


def _execution_request_with_context(
    request: Mapping[str, Any],
    context: Mapping[str, str],
) -> dict[str, Any]:
    payload = dict(request)
    for key, value in context.items():
        if not _text(payload.get(key)):
            payload[key] = value
    return payload


def runtime_execution_requests_from_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    allowed_tools: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(metadata, Mapping):
        return []
    return runtime_execution_requests_from_envelope_payload(
        metadata.get("yachiyo_execution_envelope"),
        allowed_tools=allowed_tools,
    )


def runtime_execution_requests_from_envelope_payload(
    envelope_payload: Any,
    *,
    allowed_tools: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    if isinstance(envelope_payload, RuntimeExecutionEnvelopeSnapshot):
        envelope = envelope_payload.model_dump(mode="json")
    elif isinstance(envelope_payload, Mapping):
        envelope = dict(envelope_payload)
    else:
        return []

    allowed = {
        str(tool or "").strip()
        for tool in (allowed_tools or [])
        if str(tool or "").strip()
    }
    requests = envelope.get("requests")
    if not isinstance(requests, list):
        return []
    projected: list[dict[str, Any]] = []
    for request in requests:
        if not isinstance(request, Mapping):
            continue
        projected_request = _tool_request_from_execution_request(request, envelope=envelope)
        tool_name = str(projected_request.get("tool") or "").strip()
        if not tool_name:
            continue
        if allowed and tool_name not in allowed:
            continue
        projected.append(projected_request)
    return projected


def _execution_request_snapshot(
    request: Mapping[str, Any],
    *,
    index: int,
    decision: PlannerDecisionSnapshot,
    steps: Mapping[str, ToolPlanStepSnapshot],
    previous_requests: Iterable[RuntimeExecutionRequestSnapshot] = (),
) -> RuntimeExecutionRequestSnapshot:
    tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
    deferred_context = _mapping(request.get("deferred_context"))
    step_id = str(
        request.get("step_id")
        or request.get("planner_step_id")
        or deferred_context.get("step_id")
        or deferred_context.get("planner_step_id")
        or ""
    ).strip()
    step = steps.get(step_id)
    capability_id = str(
        request.get("capability_id")
        or deferred_context.get("capability_id")
        or (step.capability_id if step is not None else "")
        or ""
    ).strip()
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    runtime_metadata = _execution_request_runtime_metadata(request, step, decision)
    replan_metadata = _execution_request_replan_metadata(
        step_id,
        step,
        decision,
        request=request,
    )
    depends_on = list(step.depends_on) if step is not None else []
    task_context = _execution_request_task_context(
        decision,
        step_id=step_id,
        depends_on=depends_on,
        runtime_stage=runtime_metadata["runtime_stage"],
    )
    desktop_contract = _desktop_execution_request_contract(
        tool_name=tool_name,
        request_input=request_input,
        request=request,
        runtime_metadata=runtime_metadata,
        step_id=step_id,
        depends_on=depends_on,
        previous_requests=previous_requests,
    )
    tool_plan_id = str(getattr(decision.plan.tool_plan, "plan_id", "") or "").strip()
    return RuntimeExecutionRequestSnapshot(
        request_id=str(
            request.get("request_id")
            or request.get("tool_call_id")
            or f"{decision.plan.plan_id}:request:{index}:{tool_name or 'tool'}"
        ),
        step_id=step_id or None,
        capability_id=capability_id or None,
        decision_id=decision.decision_id,
        plan_id=decision.plan.plan_id,
        tool_plan_id=(
            tool_plan_id
            if tool_plan_id and tool_plan_id != decision.plan.plan_id
            else None
        ),
        intent_kind=str(decision.selected_intent.kind or "") or None,
        core_id=task_context["core_id"] or None,
        workspace_id=task_context["workspace_id"] or None,
        group_run_id=_optional_text(request.get("group_run_id")),
        run_group_id=_optional_text(request.get("run_group_id")),
        group_id=_optional_text(request.get("group_id")),
        workflow_run_id=_optional_text(request.get("workflow_run_id")),
        workflow_id=_optional_text(request.get("workflow_id")),
        workflow_node_id=_optional_text(request.get("workflow_node_id")),
        workflow_node_label=_optional_text(request.get("workflow_node_label")),
        workflow_node_kind=_optional_text(request.get("workflow_node_kind")),
        tool_name=tool_name or "tool",
        protocol=str(request.get("protocol") or "json_fallback"),
        input=dict(request_input),
        planning_reason=str(request.get("planning_reason") or ""),
        approval_required=bool(
            request.get("approval_required")
            or (step.approval_required if step is not None else False)
        ),
        continue_to_model=bool(request.get("continue_to_model")),
        deferred_tool=_optional_text(request.get("deferred_tool")),
        deferred_input=_mapping(request.get("deferred_input")),
        deferred_context=deferred_context,
        deferred_continuation=[
            dict(item) for item in _mapping_list(request.get("deferred_continuation"))
        ],
        depends_on=depends_on,
        fallback_tools=list(step.fallback_tools) if step is not None else [],
        status=str(request.get("status") or (step.status if step is not None else "planned")),
        runtime_doctrine=runtime_metadata["runtime_doctrine"],
        runtime_stage=runtime_metadata["runtime_stage"],
        runtime_role=runtime_metadata["runtime_role"],
        requires_observation=runtime_metadata["requires_observation"],
        requires_post_action_verification=runtime_metadata[
            "requires_post_action_verification"
        ],
        replan_triggers=replan_metadata["replan_triggers"],
        replan_signal_ids=replan_metadata["replan_signal_ids"],
        followup_target=_mapping(request.get("followup_target")),
        action_target=(
            _mapping(request.get("action_target"))
            or desktop_contract["action_target"]
        ),
        observation_evidence=(
            _mapping(request.get("observation_evidence"))
            or desktop_contract["observation_evidence"]
        ),
        observation_retry=(
            _mapping(request.get("observation_retry"))
            or desktop_contract["observation_retry"]
        ),
        task_todo=task_context["task_todo"] or _mapping(deferred_context.get("task_todo")),
        task_checkpoints=(
            task_context["task_checkpoints"]
            or [dict(item) for item in _mapping_list(deferred_context.get("task_checkpoints"))]
        ),
        task_workspace_items=(
            task_context["task_workspace_items"]
            or [
                dict(item)
                for item in _mapping_list(deferred_context.get("task_workspace_items"))
            ]
        ),
        task_verification_targets=(
            task_context["task_verification_targets"]
            or [
                dict(item)
                for item in _mapping_list(deferred_context.get("task_verification_targets"))
            ]
        ),
        source=str(request.get("source") or "runtime_planner"),
    )


def _tool_request_from_execution_request(
    request: Mapping[str, Any],
    *,
    envelope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    payload: dict[str, Any] = {
        "protocol": str(request.get("protocol") or "json_fallback"),
        "tool": str(request.get("tool_name") or request.get("tool") or "").strip(),
        "input": dict(request_input),
        "source": str(request.get("source") or "runtime_planner"),
        "planning_reason": str(request.get("planning_reason") or ""),
    }
    for key in (
        "request_id",
        "step_id",
        "capability_id",
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "intent_kind",
        "core_id",
        "workspace_id",
        "group_run_id",
        "run_group_id",
        "group_id",
        "workflow_run_id",
        "workflow_id",
        "workflow_node_id",
        "workflow_node_label",
        "workflow_node_kind",
        "approval_required",
        "continue_to_model",
        "deferred_tool",
        "deferred_input",
        "deferred_context",
        "deferred_continuation",
        "depends_on",
        "fallback_tools",
        "status",
        "runtime_doctrine",
        "runtime_stage",
        "runtime_role",
        "requires_observation",
        "requires_post_action_verification",
        "replan_triggers",
        "replan_signal_ids",
        "task_todo",
        "task_checkpoints",
        "task_workspace_items",
        "task_verification_targets",
        "action_target",
        "observation_evidence",
        "observation_retry",
    ):
        value = request.get(key)
        if value not in (None, "", [], {}):
            payload[key] = value
    if isinstance(envelope, Mapping):
        _apply_envelope_task_context(payload, envelope)
    return payload


_SELECTED_DESKTOP_APP_NAME = "<selected app from desktop.list_apps>"
_SELECTED_RUNNING_DESKTOP_APP_NAME = "<selected app from desktop.running_apps>"
_DESKTOP_APP_SELECTION_SOURCE = "desktop.list_apps"
_DESKTOP_RUNNING_APP_SELECTION_SOURCE = "desktop.running_apps"
_DESKTOP_APP_SELECTION_SOURCES = {
    _DESKTOP_APP_SELECTION_SOURCE,
    _DESKTOP_RUNNING_APP_SELECTION_SOURCE,
}


def _desktop_execution_request_contract(
    *,
    tool_name: str,
    request_input: Mapping[str, Any],
    request: Mapping[str, Any],
    runtime_metadata: Mapping[str, Any],
    step_id: str,
    depends_on: list[str],
    previous_requests: Iterable[RuntimeExecutionRequestSnapshot],
) -> dict[str, dict[str, Any]]:
    scope = _desktop_app_selection_scope(request_input, request)
    runtime_stage = str(runtime_metadata.get("runtime_stage") or "").strip()
    if not scope and _desktop_request_can_inherit_selection_scope(
        tool_name,
        runtime_stage,
    ):
        scope = _desktop_app_selection_scope_from_previous_requests(
            depends_on,
            previous_requests,
        )
    if not scope:
        return {
            "action_target": {},
            "observation_evidence": {},
            "observation_retry": {},
        }

    action = _desktop_request_action(tool_name, runtime_stage)
    action_target = {
        "kind": "desktop_app",
        "action": action,
        **scope,
    }
    if step_id:
        action_target["step_id"] = step_id
    if runtime_stage == "verify":
        action_target["verified_step_ids"] = list(depends_on)

    observation_evidence = {
        "source_tool": (
            scope.get("selection_source")
            if runtime_stage != "verify"
            else (tool_name or "runtime_verification")
        ),
        **scope,
    }
    observation_retry = _desktop_observation_retry(
        tool_name=tool_name,
        request_input=request_input,
        runtime_stage=runtime_stage,
        scope=scope,
    )
    return {
        "action_target": _non_empty_mapping(action_target),
        "observation_evidence": _non_empty_mapping(observation_evidence),
        "observation_retry": observation_retry,
    }


def _desktop_app_selection_scope(
    request_input: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    selection_source = str(
        request_input.get("selection_source")
        or request_input.get("app_selection_source")
        or ""
    ).strip()
    input_resolution = (
        request.get("input_resolution")
        if isinstance(request.get("input_resolution"), Mapping)
        else {}
    )
    resolution_source = str(input_resolution.get("source_tool") or "").strip()
    app_name = str(
        request_input.get("app_name")
        or input_resolution.get("resolved_app_name")
        or ""
    ).strip()
    query = str(
        request_input.get("query")
        or input_resolution.get("requested_app_name")
        or input_resolution.get("query")
        or ("" if _desktop_app_placeholder_selection_source(app_name) else app_name)
    ).strip()
    if selection_source not in _DESKTOP_APP_SELECTION_SOURCES:
        selection_source = ""
    if resolution_source not in _DESKTOP_APP_SELECTION_SOURCES:
        resolution_source = ""
    placeholder_source = _desktop_app_placeholder_selection_source(app_name)
    source = selection_source or resolution_source or placeholder_source
    if not source:
        return {}
    scope: dict[str, Any] = {
        "selection_source": source,
    }
    if app_name:
        scope["app_name"] = app_name
    if query:
        scope["query"] = query
    resolved_app = str(input_resolution.get("resolved_app_name") or "").strip()
    if resolved_app:
        scope["resolved_app_name"] = resolved_app
    resolved_path = str(input_resolution.get("resolved_app_path") or "").strip()
    if resolved_path:
        scope["resolved_app_path"] = resolved_path
    return scope


def _desktop_app_selection_scope_from_previous_requests(
    depends_on: list[str],
    previous_requests: Iterable[RuntimeExecutionRequestSnapshot],
) -> dict[str, Any]:
    dependency_ids = {
        str(value or "").strip()
        for value in depends_on
        if str(value or "").strip()
    }
    fallback_scope: dict[str, Any] = {}
    for previous in reversed(list(previous_requests)):
        request_input = previous.input if isinstance(previous.input, Mapping) else {}
        scope = _desktop_app_selection_scope(
            request_input,
            {
                "input_resolution": {},
            },
        )
        if not scope:
            continue
        if not fallback_scope:
            fallback_scope = scope
        previous_step_id = str(previous.step_id or "").strip()
        if dependency_ids and previous_step_id in dependency_ids:
            return scope
    return fallback_scope


def _desktop_request_action(tool_name: str, runtime_stage: str) -> str:
    clean_tool = str(tool_name or "").strip()
    if runtime_stage == "verify":
        return "verify_after_action"
    if clean_tool in {"app.open", "desktop.open_app"}:
        return "open_app"
    if clean_tool in {"app.focus", "desktop.focus_app"}:
        return "focus_app"
    if clean_tool in {"desktop.search_submit", "desktop.submit_foreground"}:
        return "submit_ui"
    if "click" in clean_tool:
        return "click_ui"
    if "type" in clean_tool:
        return "type_ui"
    if "shortcut" in clean_tool or "hotkey" in clean_tool:
        return "keyboard_shortcut"
    if "key" in clean_tool:
        return "keyboard_key"
    if "scroll" in clean_tool:
        return "scroll_ui"
    return clean_tool or "desktop_operation"


def _desktop_request_can_inherit_selection_scope(
    tool_name: str,
    runtime_stage: str,
) -> bool:
    if str(runtime_stage or "").strip() == "verify":
        return True
    return str(tool_name or "").strip() in {
        "desktop.active_window",
        "desktop.search_submit",
        "desktop.submit_foreground",
        "desktop.verify",
        "desktop.ui_elements",
        "desktop.read_ui",
        "screen.capture",
    }


def _desktop_observation_retry(
    *,
    tool_name: str,
    request_input: Mapping[str, Any],
    runtime_stage: str,
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    if runtime_stage == "verify":
        retry_input = {
            key: request_input[key]
            for key in ("app_name", "role_filter", "limit", "reason")
            if key in request_input and request_input[key] not in (None, "")
        }
        if not retry_input:
            retry_input = {
                key: scope[key]
                for key in ("app_name", "query", "selection_source")
                if key in scope and scope[key] not in (None, "")
            }
        return _non_empty_mapping(
            {
                "from_tool": tool_name,
                "tool": tool_name,
                "input": retry_input,
                "reason": "verification_failed",
            }
        )
    query = str(scope.get("query") or scope.get("app_name") or "").strip()
    selection_source = str(scope.get("selection_source") or _DESKTOP_APP_SELECTION_SOURCE).strip()
    retry_input: dict[str, Any] = (
        {}
        if selection_source == _DESKTOP_RUNNING_APP_SELECTION_SOURCE
        else {"limit": 20}
    )
    if query and selection_source != _DESKTOP_RUNNING_APP_SELECTION_SOURCE:
        retry_input["query"] = query
    return _non_empty_mapping(
        {
            "from_tool": selection_source,
            "tool": selection_source,
            "input": retry_input,
            "reason": "resolve_desktop_app",
        }
    )


def _desktop_app_placeholder_selection_source(app_name: str) -> str:
    clean_name = str(app_name or "").strip()
    if clean_name == _SELECTED_RUNNING_DESKTOP_APP_NAME:
        return _DESKTOP_RUNNING_APP_SELECTION_SOURCE
    if clean_name == _SELECTED_DESKTOP_APP_NAME:
        return _DESKTOP_APP_SELECTION_SOURCE
    return ""


def _non_empty_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if item not in (None, "", [], {})
    }


def _apply_envelope_task_context(
    payload: dict[str, Any],
    envelope: Mapping[str, Any],
) -> None:
    for key in ("decision_id", "plan_id", "intent_kind"):
        value = envelope.get(key)
        if key not in payload and value not in (None, "", [], {}):
            payload[key] = value

    task_core = _task_core_payload(envelope)
    if not task_core:
        return
    if "core_id" not in payload:
        core_id = str(task_core.get("core_id") or "").strip()
        if core_id:
            payload["core_id"] = core_id
    workspace_id = _task_workspace_id(task_core)
    if workspace_id and "workspace_id" not in payload:
        payload["workspace_id"] = workspace_id

    step_id = str(payload.get("step_id") or payload.get("planner_step_id") or "").strip()
    if not step_id:
        return

    todo = _task_todo_for_step(task_core, step_id)
    if todo and "task_todo" not in payload:
        payload["task_todo"] = todo
    checkpoints = _task_checkpoints_for_step(task_core, step_id)
    if checkpoints and "task_checkpoints" not in payload:
        payload["task_checkpoints"] = checkpoints
    workspace_items = _task_workspace_items_for_step(task_core, step_id)
    if workspace_items and "task_workspace_items" not in payload:
        payload["task_workspace_items"] = workspace_items
    verification_targets = _task_verification_targets_for_request(task_core, payload)
    if verification_targets and "task_verification_targets" not in payload:
        payload["task_verification_targets"] = verification_targets


def _execution_request_task_context(
    decision: PlannerDecisionSnapshot,
    *,
    step_id: str,
    depends_on: list[str],
    runtime_stage: str,
) -> dict[str, Any]:
    task_core = _task_core_payload_from_decision(decision)
    if not task_core:
        return {
            "core_id": "",
            "workspace_id": "",
            "task_todo": {},
            "task_checkpoints": [],
            "task_workspace_items": [],
            "task_verification_targets": [],
        }
    payload = {
        "step_id": step_id,
        "runtime_stage": runtime_stage,
        "depends_on": list(depends_on),
    }
    return {
        "core_id": str(task_core.get("core_id") or "").strip(),
        "workspace_id": _task_workspace_id(task_core),
        "task_todo": _task_todo_for_step(task_core, step_id),
        "task_checkpoints": _task_checkpoints_for_step(task_core, step_id),
        "task_workspace_items": _task_workspace_items_for_step(task_core, step_id),
        "task_verification_targets": _task_verification_targets_for_request(
            task_core,
            payload,
        ),
    }


def _task_core_payload_from_decision(
    decision: PlannerDecisionSnapshot,
) -> Mapping[str, Any]:
    task_core = getattr(decision.plan, "task_core", None)
    if task_core is None:
        return {}
    model_dump = getattr(task_core, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json")
        return payload if isinstance(payload, Mapping) else {}
    return task_core if isinstance(task_core, Mapping) else {}


def _task_core_payload(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    task_core = envelope.get("task_core")
    return task_core if isinstance(task_core, Mapping) else {}


def _task_workspace_id(task_core: Mapping[str, Any]) -> str:
    workspace = task_core.get("workspace")
    if not isinstance(workspace, Mapping):
        return ""
    return str(workspace.get("workspace_id") or "").strip()


def _task_todo_for_step(
    task_core: Mapping[str, Any],
    step_id: str,
) -> dict[str, Any]:
    for todo in _mapping_list(task_core.get("todos")):
        if str(todo.get("step_id") or "").strip() == step_id:
            return dict(todo)
    return {}


def _task_checkpoints_for_step(
    task_core: Mapping[str, Any],
    step_id: str,
) -> list[dict[str, Any]]:
    return [
        dict(checkpoint)
        for checkpoint in _mapping_list(task_core.get("checkpoints"))
        if str(checkpoint.get("after_step_id") or "").strip() == step_id
    ]


def _task_workspace_items_for_step(
    task_core: Mapping[str, Any],
    step_id: str,
) -> list[dict[str, Any]]:
    workspace = task_core.get("workspace")
    if not isinstance(workspace, Mapping):
        return []
    return [
        dict(item)
        for item in _mapping_list(workspace.get("items"))
        if str(item.get("source_step_id") or "").strip() == step_id
    ]


def _task_verification_targets_for_request(
    task_core: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if str(payload.get("runtime_stage") or "").strip() != "verify":
        return []
    targets: list[dict[str, Any]] = []
    for dependency in _string_list(payload.get("depends_on")):
        todo = _task_todo_for_step(task_core, dependency)
        checkpoints = _task_checkpoints_for_step(task_core, dependency)
        workspace_items = _task_workspace_items_for_step(task_core, dependency)
        if not todo and not checkpoints and not workspace_items:
            continue
        target: dict[str, Any] = {"step_id": dependency}
        if todo:
            target["todo"] = todo
        if checkpoints:
            target["checkpoints"] = checkpoints
        if workspace_items:
            target["workspace_items"] = workspace_items
        targets.append(target)
    return targets


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def _string_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return _string_list(value)
    text = _text(value)
    return [text] if text else []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _execution_envelope_runtime_metadata(
    requests: list[RuntimeExecutionRequestSnapshot],
    decision: PlannerDecisionSnapshot,
) -> dict[str, Any]:
    stage_counts: dict[str, int] = {}
    doctrine = ""
    for request in requests:
        stage = str(request.runtime_stage or "").strip()
        if not stage:
            continue
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        doctrine = doctrine or str(request.runtime_doctrine or "").strip()
    if not doctrine and stage_counts:
        doctrine = "discover_operate_verify"
    return {
        "runtime_doctrine": doctrine,
        "runtime_stage_counts": stage_counts,
        "replan_signal_count": _task_replan_signal_count(decision),
    }


def _execution_request_runtime_metadata(
    request: Mapping[str, Any],
    step: ToolPlanStepSnapshot | None,
    decision: PlannerDecisionSnapshot,
) -> dict[str, Any]:
    step_id = _text(
        request.get("step_id")
        or request.get("planner_step_id")
        or (step.step_id if step is not None else "")
    )
    metadata = {
        **_task_core_step_runtime_metadata(decision, step_id),
        **_mapping_subset(
            request,
            (
                "runtime_doctrine",
                "runtime_stage",
                "runtime_role",
                "requires_observation",
                "requires_post_action_verification",
            ),
        ),
    }
    runtime_stage = _text(metadata.get("runtime_stage"))
    return {
        "runtime_doctrine": _text(metadata.get("runtime_doctrine")),
        "runtime_stage": runtime_stage,
        "runtime_role": _text(metadata.get("runtime_role")),
        "requires_observation": bool(metadata.get("requires_observation")),
        "requires_post_action_verification": bool(
            metadata.get("requires_post_action_verification")
        ),
    }


def _execution_request_replan_metadata(
    step_id: str,
    step: ToolPlanStepSnapshot | None,
    decision: PlannerDecisionSnapshot,
    *,
    request: Mapping[str, Any] | None = None,
) -> dict[str, list[str]]:
    clean_step_id = _text(step_id or (step.step_id if step is not None else ""))
    signal_ids: list[str] = []
    triggers: list[str] = []
    if request is not None:
        triggers.extend(_string_values(request.get("replan_triggers")))
        triggers.extend(_string_values(request.get("replan_trigger")))
        signal_ids.extend(_string_values(request.get("replan_signal_ids")))
        signal_ids.extend(_string_values(request.get("replan_signal_id")))
        signal_ids.extend(_string_values(request.get("replan_request_id")))
    for signal in _task_replan_signals(decision):
        if _text(signal.source_step_id) != clean_step_id:
            continue
        signal_id = _text(signal.signal_id)
        trigger = _text(signal.trigger)
        if signal_id:
            signal_ids.append(signal_id)
        if trigger:
            triggers.append(trigger)
    return {
        "replan_triggers": _dedupe(triggers),
        "replan_signal_ids": _dedupe(signal_ids),
    }


def _task_core_step_runtime_metadata(
    decision: PlannerDecisionSnapshot,
    step_id: str,
) -> dict[str, Any]:
    if not step_id:
        return {}
    task_core = getattr(decision.plan, "task_core", None)
    if task_core is None:
        return {}
    for todo in list(getattr(task_core, "todos", []) or []):
        if _text(getattr(todo, "step_id", None)) == step_id:
            metadata = _runtime_metadata_subset(getattr(todo, "metadata", {}))
            if metadata:
                return metadata
    for checkpoint in list(getattr(task_core, "checkpoints", []) or []):
        if _text(getattr(checkpoint, "after_step_id", None)) == step_id:
            metadata = _runtime_metadata_subset(getattr(checkpoint, "payload", {}))
            if metadata:
                return metadata
    workspace = getattr(task_core, "workspace", None)
    for item in list(getattr(workspace, "items", []) or []):
        if _text(getattr(item, "source_step_id", None)) == step_id:
            metadata = _runtime_metadata_subset(getattr(item, "metadata", {}))
            if metadata:
                return metadata
    return {}


def _runtime_metadata_subset(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return _mapping_subset(
        value,
        (
            "runtime_doctrine",
            "runtime_stage",
            "runtime_role",
            "requires_observation",
            "requires_post_action_verification",
        ),
    )


def _mapping_subset(value: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {key: value[key] for key in keys if key in value}


def _task_replan_signals(decision: PlannerDecisionSnapshot) -> list[Any]:
    task_core = getattr(decision.plan, "task_core", None)
    if task_core is None:
        return []
    return list(getattr(task_core, "replan_signals", []) or [])


def _task_replan_signal_count(decision: PlannerDecisionSnapshot) -> int:
    return len(_task_replan_signals(decision))


def _allowed_tools(
    decision: PlannerDecisionSnapshot,
    allowed_tools: Iterable[str] | None,
) -> list[str]:
    explicit = [
        str(tool or "").strip()
        for tool in (allowed_tools or [])
        if str(tool or "").strip()
    ]
    if explicit:
        return explicit
    tools: list[str] = []
    for step in decision.plan.tool_plan.steps:
        tool_name = str(step.tool_name or "").strip()
        if tool_name:
            tools.append(tool_name)
        tools.extend(
            str(tool or "").strip()
            for tool in step.fallback_tools
            if str(tool or "").strip()
        )
    return _dedupe(tools)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _steps_by_id(
    decision: PlannerDecisionSnapshot,
) -> dict[str, ToolPlanStepSnapshot]:
    return {
        str(step.step_id or "").strip(): step
        for step in decision.plan.tool_plan.steps
        if str(step.step_id or "").strip()
    }


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result
