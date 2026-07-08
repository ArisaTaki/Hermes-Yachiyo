"""Runtime execution envelopes derived from planner decisions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import (
    DesktopExecutionLoopSnapshot,
    DesktopExecutionRouteSnapshot,
    PlannerDecisionSnapshot,
    RuntimeCheckpointPolicySnapshot,
    RuntimeExecutionEnvelopeSnapshot,
    RuntimeExecutionRequestSnapshot,
    SandboxDesktopProviderSnapshot,
    ToolPlanStepSnapshot,
)
from .desktop_execution_policy import (
    desktop_foreground_provider_route_requested,
    desktop_readonly_provider_route_requested,
    desktop_execution_route_decision,
    is_readonly_desktop_provider_tool,
    sandbox_desktop_provider_status,
    sandbox_desktop_provider_can_execute_tool,
)
from .app_name_hints import legacy_app_name_hint
from .planner_execution import (
    planner_full_plan_execution_tool_requests,
    planner_tool_requests_for_decision,
)
from .policy import desktop_tool_execution_mode_for_input
from .task_progress_snapshots import task_progress_summary_from_task_core

_NON_EXECUTABLE_REQUEST_STATUSES = {
    "blocked",
    "cancelled",
    "canceled",
    "completed",
    "denied",
    "expired",
    "failed",
    "rejected",
    "recovered",
    "skipped",
    "unavailable",
}


def runtime_execution_envelope_from_decision(
    decision: PlannerDecisionSnapshot | None,
    *,
    allowed_tools: Iterable[str] | None = None,
    direct: bool = False,
    full_plan: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> RuntimeExecutionEnvelopeSnapshot | None:
    if decision is None:
        return None
    clean_allowed = _allowed_tools(decision, allowed_tools)
    request_payloads = (
        planner_full_plan_execution_tool_requests(
            _full_plan_tool_requests_from_decision(
                decision,
                clean_allowed,
                metadata=metadata,
            ),
            clean_allowed,
        )
        if full_plan and _supports_full_plan_projection(decision)
        else planner_tool_requests_for_decision(
            decision,
            clean_allowed,
            direct=direct,
            execution_normalized=True,
            metadata=metadata,
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
    sandbox_provider = _sandbox_provider_for_envelope(requests)
    desktop_execution_route = _desktop_execution_route_for_envelope(requests)
    desktop_provider_session = _desktop_provider_session_for_envelope(
        requests,
        metadata=metadata,
    )
    return RuntimeExecutionEnvelopeSnapshot(
        envelope_id=f"execution-envelope-{decision.plan.plan_id}",
        decision_id=decision.decision_id,
        plan_id=decision.plan.plan_id,
        intent_kind=str(decision.selected_intent.kind or ""),
        capability_plan=decision.plan.capability_plan,
        requests=requests,
        task_core=decision.plan.task_core,
        task_progress=task_progress_summary_from_task_core(decision.plan.task_core),
        approvals_required=list(tool_plan.approvals_required),
        artifacts_expected=list(tool_plan.artifacts_expected),
        open_questions=list(tool_plan.open_questions),
        route_to_studio=bool(decision.plan.route_to_studio),
        sandbox_provider=sandbox_provider,
        desktop_execution_route=desktop_execution_route,
        desktop_provider_session=desktop_provider_session,
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
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
        direct=direct,
        full_plan=full_plan,
        metadata=metadata,
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
    task_workspace_context = _task_workspace_context(context)
    if not request_context and not task_workspace_context:
        return payload

    requests = payload.get("requests")
    if request_context and isinstance(requests, list):
        payload["requests"] = [
            _execution_request_with_context(request, request_context)
            if isinstance(request, Mapping)
            else request
            for request in requests
        ]
    if task_workspace_context:
        payload = _execution_envelope_task_core_with_context(
            payload,
            task_workspace_context,
        )
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
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    request_metadata = _runtime_request_metadata_from_metadata(metadata)
    for step in list(decision.plan.tool_plan.steps or []):
        tool_name = _text(getattr(step, "tool_name", None))
        if not tool_name or tool_name not in allowed_tools:
            continue
        status = _text(getattr(step, "status", None)) or "planned"
        if status in {"unavailable", "skipped"}:
            continue
        input_preview = getattr(step, "input_preview", None)
        raw_request_input = (
            dict(input_preview) if isinstance(input_preview, Mapping) else {}
        )
        request_input = _executable_request_input(tool_name, raw_request_input)
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
        request.update(request_metadata)
        runtime_stage = _text(
            _task_core_step_runtime_metadata(decision, step_id).get("runtime_stage")
        )
        if runtime_stage == "verify":
            request["source"] = "runtime_verification"
            request["runtime_stage"] = "verify"
            request["continue_to_model"] = True
        if _request_needs_model_materialization(tool_name, raw_request_input):
            request["continue_to_model"] = True
        requests.append(request)
    return requests


def _executable_request_input(
    tool_name: str,
    request_input: Mapping[str, Any],
) -> dict[str, Any]:
    clean_tool = _text(tool_name)
    payload = dict(request_input)
    if clean_tool in {"workspace.read", "fs.read_file", "file.read"}:
        path = _text(payload.get("path"))
        if not path:
            return {}
        payload["path"] = path
        return payload
    return payload


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
    if tool_name == "workspace.write_patch":
        if any(
            str(request_input.get(key) or "").strip()
            for key in ("patch", "diff", "content")
        ):
            return False
        if any(request_input.get(key) for key in ("changes", "edits", "operations")):
            return False
        return bool(
            request_input.get("patch_source")
            or request_input.get("diff_source")
            or request_input.get("body_source")
            or request_input.get("mode")
        )
    if tool_name in {"terminal.run", "python.run"}:
        return _command_request_needs_model_materialization(tool_name, request_input)
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


def _command_request_needs_model_materialization(
    tool_name: str,
    request_input: Mapping[str, Any],
) -> bool:
    command = str(request_input.get("command") or "").strip()
    code = str(request_input.get("code") or "").strip()
    if tool_name == "python.run" and code:
        return False
    if command and not _command_looks_like_planner_placeholder(command):
        return False
    if _command_looks_like_planner_placeholder(command):
        return True
    return any(
        request_input.get(key)
        for key in (
            "body_source",
            "file_type",
            "operation",
            "path",
            "paths",
            "pattern",
            "query",
            "selection",
            "source",
            "source_path",
        )
    )


def _command_looks_like_planner_placeholder(command: str) -> bool:
    value = str(command or "").strip().lower()
    if not value:
        return False
    return any(
        marker in value
        for marker in (
            "# analyze captured tabular data",
            "# inspect data, compute summary, generate charts",
            "# inspect data",
            "todo:",
            "<model",
            "<generated",
        )
    )


def _runtime_request_metadata_from_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}
    payload: dict[str, Any] = {}
    if _metadata_truthy(
        metadata,
        "desktop_provider_health_probe",
        "probe_desktop_provider_health",
        "sandbox_provider_health_probe",
    ):
        payload["desktop_provider_health_probe"] = True
    if _metadata_truthy(
        metadata,
        "desktop_provider_route_readonly",
        "desktop_provider_readonly_route",
        "route_readonly_desktop_provider",
    ):
        payload["desktop_provider_route_readonly"] = True
    if _metadata_truthy(
        metadata,
        "desktop_provider_route_foreground",
        "desktop_provider_foreground_route",
        "route_foreground_desktop_provider",
    ):
        payload["desktop_provider_route_foreground"] = True
    if _metadata_truthy(
        metadata,
        "desktop_provider_local_native",
        "desktop_provider_local",
        "local_desktop_provider",
    ):
        payload["desktop_provider_local_native"] = True
    if _metadata_truthy(
        metadata,
        "allow_user_foreground_takeover",
        "desktop_allow_user_foreground_takeover",
        "allow_nonisolated_desktop_provider",
    ):
        payload["allow_user_foreground_takeover"] = True
    for policy_key in (
        "desktop_execution_policy",
        "yachiyo_desktop_execution_policy",
        "desktop_interaction_policy",
    ):
        policy = metadata.get(policy_key)
        if isinstance(policy, Mapping):
            payload["desktop_execution_policy"] = dict(policy)
            break
        if isinstance(policy, str) and policy.strip():
            payload["desktop_execution_policy"] = {"mode": policy.strip()}
            break
    provider = metadata.get("sandbox_provider") or metadata.get(
        "sandbox_desktop_provider"
    )
    if isinstance(provider, Mapping):
        payload["sandbox_provider"] = dict(provider)
    desktop_provider_session = _desktop_provider_session_from_metadata(metadata)
    if desktop_provider_session:
        payload["desktop_provider_session"] = desktop_provider_session
    return payload


def _desktop_provider_session_from_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}
    session = metadata.get("desktop_provider_session")
    if isinstance(session, Mapping):
        return dict(session)
    nested_metadata = metadata.get("metadata")
    if isinstance(nested_metadata, Mapping) and nested_metadata is not metadata:
        return _desktop_provider_session_from_metadata(nested_metadata)
    return {}


def _metadata_truthy(
    metadata: Mapping[str, Any] | None,
    *keys: str,
) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    for key in keys:
        value = metadata.get(key)
        if value is True:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    nested_metadata = metadata.get("metadata")
    if isinstance(nested_metadata, Mapping) and nested_metadata is not metadata:
        return _metadata_truthy(nested_metadata, *keys)
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

_TASK_WORKSPACE_CONTEXT_KEYS = {
    "task_id",
    "run_id",
    "agent_id",
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


def _task_workspace_context(context: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(context, Mapping):
        return {}
    return {
        key: text
        for key in _TASK_WORKSPACE_CONTEXT_KEYS
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


def _execution_envelope_task_core_with_context(
    envelope: Mapping[str, Any],
    context: Mapping[str, str],
) -> dict[str, Any]:
    task_core = envelope.get("task_core")
    if not isinstance(task_core, Mapping):
        return dict(envelope)
    workspace = task_core.get("workspace")
    if not isinstance(workspace, Mapping):
        return dict(envelope)
    workspace_context = (
        dict(workspace.get("context"))
        if isinstance(workspace.get("context"), Mapping)
        else {}
    )
    updated_context = {
        **context,
        **{
            str(key): value
            for key, value in workspace_context.items()
            if str(key).strip()
        },
    }
    return {
        **dict(envelope),
        "task_core": {
            **dict(task_core),
            "workspace": {
                **dict(workspace),
                "context": updated_context,
            },
        },
    }


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
        if _request_status_is_non_executable(request):
            continue
        projected_request = _tool_request_from_execution_request(request, envelope=envelope)
        tool_name = str(projected_request.get("tool") or "").strip()
        if not tool_name:
            continue
        if allowed and tool_name not in allowed:
            continue
        projected.append(projected_request)
    return projected


def _request_status_is_non_executable(request: Mapping[str, Any]) -> bool:
    return str(request.get("status") or "").strip() in _NON_EXECUTABLE_REQUEST_STATUSES


def _sandbox_provider_for_envelope(
    requests: Iterable[RuntimeExecutionRequestSnapshot],
) -> SandboxDesktopProviderSnapshot | None:
    for request in requests:
        if request.sandbox_provider is not None:
            return request.sandbox_provider
    return None


def _desktop_execution_route_for_envelope(
    requests: Iterable[RuntimeExecutionRequestSnapshot],
) -> DesktopExecutionRouteSnapshot | None:
    for request in requests:
        if request.desktop_execution_route is not None:
            return request.desktop_execution_route
    return None


def _desktop_provider_session_for_envelope(
    requests: Iterable[RuntimeExecutionRequestSnapshot],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata_session = _desktop_provider_session_from_metadata(metadata)
    if metadata_session:
        return metadata_session
    for request in requests:
        if request.desktop_provider_session:
            return dict(request.desktop_provider_session)
    return {}


def _sandbox_provider_for_request(
    request: Mapping[str, Any],
    *,
    tool_name: str,
    execution_mode: Any,
    desktop_execution_policy: Mapping[str, Any] | None,
) -> SandboxDesktopProviderSnapshot | None:
    explicit_provider = _mapping(request.get("sandbox_provider")) or _mapping(
        request.get("sandbox_desktop_provider")
    )
    if explicit_provider:
        return SandboxDesktopProviderSnapshot.model_validate(
            sandbox_desktop_provider_status({"sandbox_provider": explicit_provider})
        )
    policy_mode = str((desktop_execution_policy or {}).get("mode") or "").strip()
    execution_mode_name = str(getattr(execution_mode, "mode", "") or "").strip()
    if (
        bool(getattr(execution_mode, "sandbox_recommended", False))
        or policy_mode == "sandbox_preferred"
        or execution_mode_name == "sandbox_preferred"
    ):
        return SandboxDesktopProviderSnapshot.model_validate(
            sandbox_desktop_provider_status(request)
        )
    if (
        desktop_readonly_provider_route_requested(request)
        and is_readonly_desktop_provider_tool(tool_name)
    ):
        provider_payload = sandbox_desktop_provider_status(request)
        if sandbox_desktop_provider_can_execute_tool(provider_payload, tool_name):
            return SandboxDesktopProviderSnapshot.model_validate(provider_payload)
    if desktop_foreground_provider_route_requested(request) and (
        bool(getattr(execution_mode, "foreground_control", False))
        or bool(getattr(execution_mode, "keyboard_mouse_capture", False))
        or execution_mode_name == "supervised_live"
    ):
        provider_payload = sandbox_desktop_provider_status(request)
        if (
            sandbox_desktop_provider_can_execute_tool(provider_payload, tool_name)
            or not bool(provider_payload.get("available"))
            or _sandbox_provider_requires_controlled_input(
                provider_payload,
                tool_name=tool_name,
                execution_mode=execution_mode,
            )
        ):
            return SandboxDesktopProviderSnapshot.model_validate(provider_payload)
    return None


def _sandbox_provider_requires_controlled_input(
    provider_payload: Mapping[str, Any],
    *,
    tool_name: str,
    execution_mode: Any,
) -> bool:
    if bool(getattr(execution_mode, "keyboard_mouse_capture", False)) and (
        provider_payload.get("keyboard_mouse_capture_supported") is False
    ):
        return True
    if bool(getattr(execution_mode, "keyboard_mouse_capture", False)) and (
        provider_payload.get("keyboard_mouse_capture_supported") is True
    ) and provider_payload.get("desktop_session_isolated") is not True:
        return True
    required_tools = set(
        _string_values(provider_payload.get("requires_real_sandbox_for"))
    )
    return str(tool_name or "").strip() in required_tools


def _desktop_execution_route_for_request(
    tool_name: str,
    request: Mapping[str, Any],
    *,
    execution_mode: Any,
    desktop_execution_policy: Mapping[str, Any] | None,
) -> DesktopExecutionRouteSnapshot | None:
    explicit_route = _mapping(request.get("desktop_execution_route"))
    if explicit_route:
        return DesktopExecutionRouteSnapshot.model_validate(explicit_route)
    if (
        desktop_execution_policy
        or bool(getattr(execution_mode, "sandbox_recommended", False))
        or (
            desktop_readonly_provider_route_requested(request)
            and is_readonly_desktop_provider_tool(tool_name)
        )
        or desktop_foreground_provider_route_requested(request)
    ):
        return DesktopExecutionRouteSnapshot.model_validate(
            desktop_execution_route_decision(
                tool_name,
                policy=desktop_execution_policy,
                execution_mode=execution_mode,
                metadata=request,
            )
        )
    return None


def _execution_request_capability_plan_item(
    decision: PlannerDecisionSnapshot,
    *,
    capability_id: str,
    step_id: str,
) -> Any | None:
    capability_plan = getattr(getattr(decision, "plan", None), "capability_plan", None)
    items = list(getattr(capability_plan, "items", None) or [])
    clean_capability_id = _text(capability_id)
    if clean_capability_id:
        for item in items:
            if _text(getattr(item, "capability_id", None)) == clean_capability_id:
                return item
    clean_step_id = _text(step_id)
    if clean_step_id:
        for item in items:
            if clean_step_id in _string_values(getattr(item, "planned_step_ids", None)):
                return item
    return None


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
    capability_plan_item = _execution_request_capability_plan_item(
        decision,
        capability_id=capability_id,
        step_id=step_id,
    )
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
    checkpoint_policy = _execution_request_checkpoint_policy(
        task_context,
        replan_metadata,
        step=step,
        runtime_metadata=runtime_metadata,
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
    desktop_loop = _desktop_execution_loop_snapshot(
        desktop_contract,
        runtime_metadata=runtime_metadata,
        task_context=task_context,
    )
    execution_mode = (
        step.execution_mode
        if step is not None and step.execution_mode is not None
        else desktop_tool_execution_mode_for_input(tool_name, request_input)
    )
    desktop_execution_policy = _mapping(request.get("desktop_execution_policy")) or None
    sandbox_provider = _sandbox_provider_for_request(
        request,
        tool_name=tool_name,
        execution_mode=execution_mode,
        desktop_execution_policy=desktop_execution_policy,
    )
    desktop_execution_route = _desktop_execution_route_for_request(
        tool_name,
        request,
        execution_mode=execution_mode,
        desktop_execution_policy=desktop_execution_policy,
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
        capability_title=_text(getattr(capability_plan_item, "title", None)),
        capability_status=_text(getattr(capability_plan_item, "status", None)),
        capability_reason=_text(getattr(capability_plan_item, "reason", None)),
        capability_selected_tools=_string_values(
            getattr(capability_plan_item, "selected_tools", None)
        ),
        capability_planned_step_ids=_string_values(
            getattr(capability_plan_item, "planned_step_ids", None)
        ),
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
        risk_level=str(
            request.get("risk_level")
            or (step.risk_level if step is not None else "")
            or "low"
        ),
        execution_mode=execution_mode,
        desktop_execution_policy=desktop_execution_policy,
        sandbox_provider=sandbox_provider,
        desktop_execution_route=desktop_execution_route,
        desktop_provider_session=_mapping(request.get("desktop_provider_session")),
        policy_reason=str(
            request.get("policy_reason") or request.get("approval_reason") or ""
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
        action_target=_merged_request_contract_mapping(
            request,
            desktop_contract,
            "action_target",
        ),
        observation_evidence=_merged_request_contract_mapping(
            request,
            desktop_contract,
            "observation_evidence",
        ),
        observation_retry=_merged_request_contract_mapping(
            request,
            desktop_contract,
            "observation_retry",
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
        verification_targets=(
            task_context["verification_targets"]
            or [
                dict(item)
                for item in _mapping_list(deferred_context.get("verification_targets"))
            ]
        ),
        task_verification_targets=(
            task_context["task_verification_targets"]
            or [
                dict(item)
                for item in _mapping_list(deferred_context.get("task_verification_targets"))
            ]
        ),
        checkpoint_policy=checkpoint_policy,
        desktop_loop=desktop_loop,
        source=str(request.get("source") or "runtime_planner"),
    )


def _merged_request_contract_mapping(
    request: Mapping[str, Any],
    desktop_contract: Mapping[str, Mapping[str, Any]],
    key: str,
) -> dict[str, Any]:
    contract_value = _mapping(desktop_contract.get(key))
    request_value = _mapping(request.get(key))
    if not contract_value:
        return request_value
    if not request_value:
        return contract_value
    return {**contract_value, **request_value}


def _tool_request_from_execution_request(
    request: Mapping[str, Any],
    *,
    envelope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tool_name = str(request.get("tool_name") or request.get("tool") or "").strip()
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    request_input = _canonical_runtime_request_input(tool_name, request_input)
    payload: dict[str, Any] = {
        "protocol": str(request.get("protocol") or "json_fallback"),
        "tool": tool_name,
        "input": dict(request_input),
        "source": str(request.get("source") or "runtime_planner"),
        "planning_reason": str(request.get("planning_reason") or ""),
    }
    for key in (
        "request_id",
        "step_id",
        "capability_id",
        "capability_title",
        "capability_status",
        "capability_reason",
        "capability_selected_tools",
        "capability_planned_step_ids",
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
        "risk_level",
        "desktop_execution_policy",
        "sandbox_provider",
        "sandbox_desktop_provider",
        "desktop_execution_route",
        "desktop_provider_session",
        "policy_reason",
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
        "verification_targets",
        "task_verification_targets",
        "checkpoint_policy",
        "desktop_loop",
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


def _canonical_runtime_request_input(
    tool_name: str,
    request_input: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(request_input)
    if not payload:
        return payload
    if str(tool_name or "").strip() not in {
        "app.open",
        "app.focus",
        "app.status",
        "desktop.open_app",
        "desktop.focus_app",
        "desktop.inspect_app",
        "desktop.windows",
        "desktop.list_windows",
        "desktop.ui_elements",
        "desktop.read_ui",
        "desktop.verify",
        "media.music_app_open_and_play",
    } and not (
        str(tool_name or "").strip().startswith("app.open_and_")
        or str(tool_name or "").strip().startswith("app.focus_and_")
    ):
        return payload
    app_name = str(payload.get("app_name") or "").strip()
    if not app_name or app_name == "企业微信":
        return payload
    canonical = str(legacy_app_name_hint(app_name) or "").strip()
    if not canonical or canonical == app_name:
        return payload
    return {**payload, "app_name": canonical}


_SELECTED_DESKTOP_APP_NAME = "<selected app from desktop.list_apps>"
_SELECTED_RUNNING_DESKTOP_APP_NAME = "<selected app from desktop.running_apps>"
_DESKTOP_APP_SELECTION_SOURCE = "desktop.list_apps"
_DESKTOP_RUNNING_APP_SELECTION_SOURCE = "desktop.running_apps"
_DESKTOP_DIRECT_APP_NAME_SOURCE = "direct_app_name"
_DESKTOP_APP_SELECTION_SOURCES = {
    _DESKTOP_APP_SELECTION_SOURCE,
    _DESKTOP_RUNNING_APP_SELECTION_SOURCE,
    _DESKTOP_DIRECT_APP_NAME_SOURCE,
}
_DESKTOP_APP_UI_ELEMENT_TYPE_TOOLS = {
    "app.focus_and_type_into_ui_element",
    "app.open_and_type_into_ui_element",
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
    target_kind = "desktop_app"
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
        scope = _desktop_direct_app_scope(
            tool_name=tool_name,
            request_input=request_input,
        )
    if not scope:
        scope = _desktop_foreground_scope(
            tool_name=tool_name,
            request_input=request_input,
            runtime_stage=runtime_stage,
            depends_on=depends_on,
            previous_requests=previous_requests,
        )
        target_kind = "desktop_foreground"
    if not scope:
        scope = _desktop_discovery_scope(
            tool_name=tool_name,
            request_input=request_input,
            runtime_stage=runtime_stage,
        )
        target_kind = "desktop_discovery"
    if not scope:
        return {
            "action_target": {},
            "observation_evidence": {},
            "observation_retry": {},
        }

    action = _desktop_request_action(tool_name, runtime_stage)
    action_target = {
        "kind": target_kind,
        "action": action,
        **scope,
        **_desktop_app_ui_element_action_scope(tool_name, request_input),
    }
    if step_id:
        action_target["step_id"] = step_id
    if runtime_stage == "verify":
        action_target["verified_step_ids"] = list(depends_on)

    observation_evidence = {
        "source_tool": _desktop_observation_source_tool(
            tool_name=tool_name,
            runtime_stage=runtime_stage,
            scope=scope,
            target_kind=target_kind,
        ),
        **scope,
    }
    observation_retry = _desktop_observation_retry(
        tool_name=tool_name,
        request_input=request_input,
        runtime_stage=runtime_stage,
        scope=scope,
        target_kind=target_kind,
    )
    return {
        "action_target": _non_empty_mapping(action_target),
        "observation_evidence": _non_empty_mapping(observation_evidence),
        "observation_retry": observation_retry,
    }


_DESKTOP_LOOP_AUTO_RETRY_TOOLS = {
    "browser.current_page",
    "browser.screenshot",
    "desktop.active_window",
    "desktop.list_apps",
    "desktop.read_ui",
    "desktop.running_apps",
    "desktop.ui_elements",
    "screen.capture",
}


def _desktop_execution_loop_snapshot(
    desktop_contract: Mapping[str, Mapping[str, Any]],
    *,
    runtime_metadata: Mapping[str, Any],
    task_context: Mapping[str, Any],
) -> DesktopExecutionLoopSnapshot | None:
    action_target = _mapping(desktop_contract.get("action_target"))
    observation_evidence = _mapping(desktop_contract.get("observation_evidence"))
    observation_retry = _mapping(desktop_contract.get("observation_retry"))
    if not any((action_target, observation_evidence, observation_retry)):
        return None
    retry_tool = _text(observation_retry.get("tool"))
    retry_reason = _text(observation_retry.get("reason"))
    retry_input = _mapping(observation_retry.get("input"))
    verification_targets = [
        *list(_mapping_list(task_context.get("verification_targets"))),
        *list(_mapping_list(task_context.get("task_verification_targets"))),
    ]
    return DesktopExecutionLoopSnapshot(
        stage=_text(runtime_metadata.get("runtime_stage")),
        role=_text(runtime_metadata.get("runtime_role")),
        action=_text(action_target.get("action")),
        target_kind=_text(action_target.get("kind")),
        selection_source=_text(
            action_target.get("selection_source")
            or observation_evidence.get("selection_source")
        ),
        app_name=_text(
            action_target.get("resolved_app_name")
            or action_target.get("app_name")
            or observation_evidence.get("resolved_app_name")
            or observation_evidence.get("app_name")
        ),
        query=_text(action_target.get("query") or observation_evidence.get("query")),
        source_tool=_text(observation_evidence.get("source_tool")),
        retry_tool=retry_tool,
        retry_reason=retry_reason,
        retry_input=retry_input,
        verification_target_step_ids=_dedupe(
            str(target.get("step_id") or "").strip()
            for target in verification_targets
        ),
        requires_observation=bool(runtime_metadata.get("requires_observation")),
        requires_post_action_verification=bool(
            runtime_metadata.get("requires_post_action_verification")
            or verification_targets
        ),
        can_auto_retry=bool(
            retry_tool
            and retry_tool in _DESKTOP_LOOP_AUTO_RETRY_TOOLS
            and retry_reason in {
                "resolve_desktop_app",
                "observe_foreground_ui",
                "verification_failed",
            }
        ),
    )


def _desktop_app_ui_element_action_scope(
    tool_name: str,
    request_input: Mapping[str, Any],
) -> dict[str, Any]:
    if str(tool_name or "").strip() not in _DESKTOP_APP_UI_ELEMENT_TYPE_TOOLS:
        return {}
    scope: dict[str, Any] = {}
    for key in ("target", "selector", "role_filter", "label"):
        value = request_input.get(key)
        if value not in (None, "", [], {}):
            scope[key] = value
    return scope


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
            scope = _desktop_app_scope_from_action_target(previous.action_target)
        if not scope:
            continue
        if not fallback_scope:
            fallback_scope = scope
        previous_step_id = str(previous.step_id or "").strip()
        if dependency_ids and previous_step_id in dependency_ids:
            return scope
    return fallback_scope


def _desktop_discovery_scope(
    *,
    tool_name: str,
    request_input: Mapping[str, Any],
    runtime_stage: str,
) -> dict[str, Any]:
    clean_tool = str(tool_name or "").strip()
    if str(runtime_stage or "").strip() != "discover":
        return {}
    if clean_tool not in {
        "desktop.list_apps",
        "desktop.running_apps",
        "desktop.ui_elements",
        "desktop.read_ui",
        "desktop.active_window",
        "desktop.windows",
        "desktop.list_windows",
        "desktop.verify",
        "screen.capture",
    }:
        return {}
    return _non_empty_mapping(
        {
            "selection_source": clean_tool,
            "query": request_input.get("query"),
            "app_name": request_input.get("app_name"),
            "title_contains": request_input.get("title_contains"),
            "role_filter": request_input.get("role_filter"),
            "target": request_input.get("target"),
            "selector": request_input.get("selector"),
            "limit": request_input.get("limit"),
            "reason": request_input.get("reason"),
        }
    )


def _desktop_foreground_scope(
    *,
    tool_name: str,
    request_input: Mapping[str, Any],
    runtime_stage: str,
    depends_on: list[str],
    previous_requests: Iterable[RuntimeExecutionRequestSnapshot],
) -> dict[str, Any]:
    if not _desktop_request_supports_foreground_target(tool_name, runtime_stage):
        return {}
    inherited = _desktop_foreground_scope_from_previous_requests(
        depends_on,
        previous_requests,
    )
    scope = {
        "target_scope": "foreground",
        **inherited,
        **_desktop_foreground_scope_from_input(request_input),
    }
    return _non_empty_mapping(scope)


def _desktop_direct_app_scope(
    *,
    tool_name: str,
    request_input: Mapping[str, Any],
) -> dict[str, Any]:
    if str(tool_name or "").strip() not in {
        "app.open",
        "app.focus",
        "app.focus_window",
        "app.status",
        "app.show",
        "app.hide",
        "app.minimize",
        "app.quit",
        "desktop.open_app",
        "desktop.focus_app",
    }:
        return {}
    app_name = _text(request_input.get("app_name"))
    if not app_name or _desktop_app_placeholder_selection_source(app_name):
        return {}
    query = _text(request_input.get("query")) or app_name
    scope = {
        "selection_source": _DESKTOP_DIRECT_APP_NAME_SOURCE,
        "app_name": app_name,
        "query": query,
    }
    title_contains = _text(request_input.get("title_contains"))
    if title_contains:
        scope["title_contains"] = title_contains
    return scope


def _desktop_foreground_scope_from_input(
    request_input: Mapping[str, Any],
) -> dict[str, Any]:
    scope: dict[str, Any] = {}
    for key in (
        "target",
        "selector",
        "role_filter",
        "title_contains",
        "label",
        "query",
        "action",
        "key",
        "direction",
    ):
        value = request_input.get(key)
        if value not in (None, "", [], {}):
            scope[key] = value
    text = _text(request_input.get("text"))
    if text:
        scope["text_preview"] = text[:120]
        scope["text_length"] = len(text)
    return scope


def _desktop_foreground_scope_from_previous_requests(
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
        target = (
            previous.action_target
            if isinstance(previous.action_target, Mapping)
            else {}
        )
        if str(target.get("kind") or "").strip() != "desktop_foreground":
            continue
        scope = {
            key: value
            for key, value in target.items()
            if key not in {"kind", "action", "step_id", "verified_step_ids"}
            and value not in (None, "", [], {})
        }
        if not scope:
            continue
        if not fallback_scope:
            fallback_scope = scope
        previous_step_id = str(previous.step_id or "").strip()
        if dependency_ids and previous_step_id in dependency_ids:
            return scope
    return fallback_scope


def _desktop_app_scope_from_action_target(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    if str(value.get("kind") or "").strip() != "desktop_app":
        return {}
    return _non_empty_mapping(
        {
            key: value.get(key)
            for key in (
                "selection_source",
                "app_name",
                "query",
                "title_contains",
                "resolved_app_name",
                "resolved_app_path",
            )
        }
    )


def _desktop_request_action(tool_name: str, runtime_stage: str) -> str:
    clean_tool = str(tool_name or "").strip()
    if runtime_stage == "verify":
        return "verify_after_action"
    if clean_tool in {"app.open", "desktop.open_app"}:
        return "open_app"
    if clean_tool in {"app.focus", "desktop.focus_app"}:
        return "focus_app"
    if clean_tool == "app.focus_window":
        return "focus_app_window"
    if clean_tool == "desktop.active_window":
        return "read_active_window"
    if clean_tool in {"desktop.windows", "desktop.list_windows"}:
        return "list_windows"
    if clean_tool in {"desktop.ui_elements", "desktop.read_ui"}:
        return "read_ui"
    if clean_tool == "desktop.list_apps":
        return "discover_apps"
    if clean_tool == "desktop.running_apps":
        return "list_running_apps"
    if clean_tool == "screen.capture":
        return "capture_screen"
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
        "desktop.click",
        "desktop.click_ui_element",
        "desktop.hotkey",
        "desktop.key",
        "desktop.safe_click",
        "desktop.safe_key",
        "desktop.safe_scroll",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.shortcut",
        "desktop.submit_foreground",
        "desktop.type",
        "desktop.type_into_ui_element",
        "desktop.type_text",
        "desktop.verify",
        "desktop.ui_elements",
        "desktop.read_ui",
        "screen.capture",
    }


def _desktop_request_supports_foreground_target(
    tool_name: str,
    runtime_stage: str,
) -> bool:
    clean_tool = str(tool_name or "").strip()
    if str(runtime_stage or "").strip() == "verify":
        return (
            clean_tool.startswith(("app.", "desktop."))
            or clean_tool == "screen.capture"
        )
    return clean_tool in {
        "desktop.active_window",
        "desktop.click",
        "desktop.click_ui_element",
        "desktop.hotkey",
        "desktop.key",
        "desktop.read_ui",
        "desktop.safe_click",
        "desktop.safe_key",
        "desktop.safe_scroll",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.shortcut",
        "desktop.submit_foreground",
        "desktop.type",
        "desktop.type_into_ui_element",
        "desktop.type_text",
        "desktop.ui_elements",
        "desktop.verify",
        "screen.capture",
    }


def _desktop_observation_source_tool(
    *,
    tool_name: str,
    runtime_stage: str,
    scope: Mapping[str, Any],
    target_kind: str,
) -> str:
    if str(runtime_stage or "").strip() == "verify":
        return tool_name or "runtime_verification"
    if target_kind == "desktop_app":
        return str(scope.get("selection_source") or tool_name or "runtime_execution")
    if target_kind == "desktop_discovery":
        return str(scope.get("selection_source") or tool_name or "runtime_discovery")
    return tool_name or "desktop.foreground"


def _desktop_observation_retry(
    *,
    tool_name: str,
    request_input: Mapping[str, Any],
    runtime_stage: str,
    scope: Mapping[str, Any],
    target_kind: str = "desktop_app",
) -> dict[str, Any]:
    if target_kind == "desktop_foreground":
        return _desktop_foreground_observation_retry(
            tool_name=tool_name,
            request_input=request_input,
            runtime_stage=runtime_stage,
            scope=scope,
        )
    if target_kind == "desktop_discovery":
        return _desktop_discovery_observation_retry(
            tool_name=tool_name,
            request_input=request_input,
            runtime_stage=runtime_stage,
            scope=scope,
        )
    if runtime_stage == "verify":
        retry_input = {
            key: request_input[key]
            for key in ("app_name", "role_filter", "limit", "reason")
            if key in request_input and request_input[key] not in (None, "")
        }
        if tool_name != "desktop.active_window" and not retry_input:
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
    if selection_source == _DESKTOP_DIRECT_APP_NAME_SOURCE:
        selection_source = _DESKTOP_APP_SELECTION_SOURCE
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


def _desktop_discovery_observation_retry(
    *,
    tool_name: str,
    request_input: Mapping[str, Any],
    runtime_stage: str,
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    clean_tool = str(tool_name or "").strip()
    if clean_tool in {"desktop.windows", "desktop.list_windows"}:
        retry_input = {
            key: request_input[key]
            for key in ("app_name", "title_contains", "limit")
            if key in request_input and request_input[key] not in (None, "")
        }
        if not retry_input:
            retry_input = {
                key: scope[key]
                for key in ("app_name", "title_contains", "limit")
                if key in scope and scope[key] not in (None, "")
            }
        return _non_empty_mapping(
            {
                "from_tool": clean_tool,
                "tool": clean_tool,
                "input": retry_input,
                "reason": "observe_windows",
            }
        )
    if clean_tool in {"desktop.ui_elements", "desktop.read_ui", "desktop.verify"}:
        retry_input = {
            key: request_input[key]
            for key in ("app_name", "role_filter", "target", "selector", "limit", "reason")
            if key in request_input and request_input[key] not in (None, "")
        }
        if not retry_input:
            retry_input = {
                key: scope[key]
                for key in ("app_name", "role_filter", "target", "selector", "limit", "reason")
                if key in scope and scope[key] not in (None, "")
            }
        return _non_empty_mapping(
            {
                "from_tool": clean_tool,
                "tool": clean_tool,
                "input": retry_input,
                "reason": (
                    "verification_failed"
                    if clean_tool == "desktop.verify" or runtime_stage == "verify"
                    else "observe_ui"
                ),
            }
        )
    if clean_tool == "desktop.active_window":
        return _non_empty_mapping(
            {
                "from_tool": clean_tool,
                "tool": clean_tool,
                "input": {},
                "reason": "observe_active_window",
            }
        )
    if clean_tool == "screen.capture":
        return _non_empty_mapping(
            {
                "from_tool": clean_tool,
                "tool": clean_tool,
                "input": {},
                "reason": "capture_screen",
            }
        )
    query = str(scope.get("query") or scope.get("app_name") or "").strip()
    retry_input: dict[str, Any] = (
        {}
        if clean_tool == _DESKTOP_RUNNING_APP_SELECTION_SOURCE
        else {"limit": 20}
    )
    if query and clean_tool != _DESKTOP_RUNNING_APP_SELECTION_SOURCE:
        retry_input["query"] = query
    return _non_empty_mapping(
        {
            "from_tool": clean_tool,
            "tool": clean_tool,
            "input": retry_input,
            "reason": "resolve_desktop_app",
        }
    )


def _desktop_foreground_observation_retry(
    *,
    tool_name: str,
    request_input: Mapping[str, Any],
    runtime_stage: str,
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    if runtime_stage == "verify":
        retry_input = {
            key: request_input[key]
            for key in ("role_filter", "limit", "reason")
            if key in request_input and request_input[key] not in (None, "")
        }
        if not retry_input:
            retry_input = {
                key: scope[key]
                for key in ("role_filter", "target", "selector", "query")
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

    retry_input = {
        key: request_input[key]
        for key in ("role_filter", "limit", "target", "selector")
        if key in request_input and request_input[key] not in (None, "")
    }
    if not retry_input:
        retry_input = {
            key: scope[key]
            for key in ("role_filter", "target", "selector", "query")
            if key in scope and scope[key] not in (None, "")
        }
    return _non_empty_mapping(
        {
            "from_tool": "desktop.ui_elements",
            "tool": "desktop.ui_elements",
            "input": retry_input,
            "reason": "observe_foreground_ui",
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
    if verification_targets and "verification_targets" not in payload:
        payload["verification_targets"] = verification_targets
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
            "verification_targets": [],
            "task_verification_targets": [],
        }
    payload = {
        "step_id": step_id,
        "runtime_stage": runtime_stage,
        "depends_on": list(depends_on),
    }
    verification_targets = _task_verification_targets_for_request(
        task_core,
        payload,
    )
    return {
        "core_id": str(task_core.get("core_id") or "").strip(),
        "workspace_id": _task_workspace_id(task_core),
        "task_todo": _task_todo_for_step(task_core, step_id),
        "task_checkpoints": _task_checkpoints_for_step(task_core, step_id),
        "task_workspace_items": _task_workspace_items_for_step(task_core, step_id),
        "verification_targets": verification_targets,
        "task_verification_targets": verification_targets,
    }


def _execution_request_checkpoint_policy(
    task_context: Mapping[str, Any],
    replan_metadata: Mapping[str, list[str]],
    *,
    step: ToolPlanStepSnapshot | None,
    runtime_metadata: Mapping[str, Any],
) -> RuntimeCheckpointPolicySnapshot | None:
    checkpoints = _mapping_list(task_context.get("task_checkpoints"))
    verification_targets = [
        *list(_mapping_list(task_context.get("verification_targets"))),
        *list(_mapping_list(task_context.get("task_verification_targets"))),
    ]
    fallback_tools = list(step.fallback_tools) if step is not None else []
    replan_triggers = _string_list(replan_metadata.get("replan_triggers"))
    replan_signal_ids = _string_list(replan_metadata.get("replan_signal_ids"))
    if not any(
        (
            checkpoints,
            verification_targets,
            fallback_tools,
            replan_triggers,
            replan_signal_ids,
        )
    ):
        return None
    return RuntimeCheckpointPolicySnapshot(
        checkpoint_ids=_dedupe(
            str(checkpoint.get("checkpoint_id") or "").strip()
            for checkpoint in checkpoints
        ),
        checkpoint_titles=_dedupe(
            str(checkpoint.get("title") or "").strip()
            for checkpoint in checkpoints
        ),
        verifies=_dedupe(
            item
            for checkpoint in checkpoints
            for item in _string_list(checkpoint.get("verifies"))
        ),
        replan_on_failure=bool(
            replan_triggers
            or replan_signal_ids
            or any(
                checkpoint.get("replan_on_failure") is not False
                for checkpoint in checkpoints
            )
        ),
        replan_triggers=replan_triggers,
        replan_signal_ids=replan_signal_ids,
        fallback_tools=_dedupe(fallback_tools),
        verification_target_step_ids=_dedupe(
            str(target.get("step_id") or "").strip()
            for target in verification_targets
        ),
        requires_approval=bool(step.approval_required if step is not None else False),
        requires_observation=bool(runtime_metadata.get("requires_observation")),
        requires_post_action_verification=bool(
            runtime_metadata.get("requires_post_action_verification")
            or verification_targets
        ),
    )


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
    if _execution_request_runtime_stage(request, decision, clean_step_id) == "verify":
        dependency_signal_metadata = _dependency_verification_replan_metadata(
            decision,
            _execution_request_dependency_step_ids(request, step),
        )
        signal_ids.extend(dependency_signal_metadata["replan_signal_ids"])
        triggers.extend(dependency_signal_metadata["replan_triggers"])
    return {
        "replan_triggers": _dedupe(triggers),
        "replan_signal_ids": _dedupe(signal_ids),
    }


def _execution_request_runtime_stage(
    request: Mapping[str, Any] | None,
    decision: PlannerDecisionSnapshot,
    step_id: str,
) -> str:
    runtime_stage = _text((request or {}).get("runtime_stage"))
    if runtime_stage:
        return runtime_stage
    return _text(
        _task_core_step_runtime_metadata(decision, step_id).get("runtime_stage")
    )


def _execution_request_dependency_step_ids(
    request: Mapping[str, Any] | None,
    step: ToolPlanStepSnapshot | None,
) -> list[str]:
    dependency_ids: list[str] = []
    if request is not None:
        dependency_ids.extend(_string_values(request.get("depends_on")))
    if step is not None:
        dependency_ids.extend(str(item or "").strip() for item in list(step.depends_on))
    return _dedupe(item for item in dependency_ids if item)


def _dependency_verification_replan_metadata(
    decision: PlannerDecisionSnapshot,
    dependency_step_ids: Iterable[str],
) -> dict[str, list[str]]:
    dependency_ids = {
        str(step_id or "").strip()
        for step_id in dependency_step_ids
        if str(step_id or "").strip()
    }
    signal_ids: list[str] = []
    triggers: list[str] = []
    for signal in _task_replan_signals(decision):
        if _text(signal.source_step_id) not in dependency_ids:
            continue
        trigger = _text(signal.trigger)
        if trigger != "verification_failed":
            continue
        signal_id = _text(signal.signal_id)
        if signal_id:
            signal_ids.append(signal_id)
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
