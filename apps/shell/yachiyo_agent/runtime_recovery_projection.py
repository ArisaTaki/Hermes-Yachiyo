"""Shared runtime retry continuation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import RuntimeExecutionEnvelopeSnapshot, RuntimeExecutionRequestSnapshot


_UI_OBSERVATION_TOOLS = {"desktop.read_ui", "desktop.ui_elements"}
_UI_MUTATION_TOOL_TOKENS = (
    "click",
    "hotkey",
    "key",
    "scroll",
    "shortcut",
    "submit",
    "type",
)
_COMPLETED_STATUSES = {
    "cancelled",
    "canceled",
    "completed",
    "denied",
    "expired",
    "recovered",
    "rejected",
    "skipped",
}


def runtime_execution_recovery_retry(
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
    retry: Mapping[str, Any],
    *,
    envelope: RuntimeExecutionEnvelopeSnapshot,
) -> dict[str, Any]:
    """Return the executable retry request for a failed runtime request."""

    clean_retry = _mapping(retry)
    if _is_ui_mutation_request(request):
        observation = _nearest_ui_observation_request(envelope, request)
        if observation is not None:
            return _retry_from_observation_request(
                observation,
                clean_retry,
                reason="observe_foreground_ui",
            )
    if _is_ui_observation_request(request):
        return _retry_from_observation_request(
            request,
            clean_retry,
            reason="observe_foreground_ui",
        )
    return clean_retry


def runtime_execution_recovery_deferred_payload(
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
    *,
    envelope: RuntimeExecutionEnvelopeSnapshot,
    retry_tool: str,
) -> dict[str, Any]:
    """Project the continuation that should run after a runtime retry succeeds."""

    deferred_tool = _first_text(_runtime_request_value(request, "deferred_tool"))
    deferred_input = _mapping(_runtime_request_value(request, "deferred_input"))
    deferred_context = _mapping(_runtime_request_value(request, "deferred_context"))
    deferred_continuation = _mapping_list(
        _runtime_request_value(request, "deferred_continuation")
    )

    if (
        not deferred_tool
        and retry_tool in _UI_OBSERVATION_TOOLS
        and _is_ui_mutation_request(request)
    ):
        deferred_tool = _first_text(_runtime_request_value(request, "tool_name"))
        deferred_input = _mapping(_runtime_request_value(request, "input"))
        deferred_context = _request_deferred_context(request)

    derived_continuation = runtime_execution_recovery_continuation_requests(
        request,
        envelope=envelope,
        retry_tool=retry_tool,
    )
    _extend_unique_continuations(deferred_continuation, derived_continuation)

    return {
        "deferred_tool": deferred_tool,
        "deferred_input": deferred_input,
        "deferred_context": deferred_context,
        "deferred_continuation": deferred_continuation,
    }


def runtime_execution_recovery_continuation_requests(
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
    *,
    envelope: RuntimeExecutionEnvelopeSnapshot,
    retry_tool: str,
) -> list[dict[str, Any]]:
    """Derive the still-pending tail of the runtime plan after a retry."""

    source_index = _request_index(envelope, request)
    if source_index < 0:
        return []
    source_step_id = _first_text(_runtime_request_value(request, "step_id"))
    chain_step_ids = {source_step_id} if source_step_id else set()
    continuation: list[dict[str, Any]] = []

    for later_request in list(envelope.requests or [])[source_index + 1 :]:
        if _request_is_completed(later_request):
            continue
        if not _request_continues_chain(later_request, chain_step_ids, continuation):
            if continuation:
                break
            continue
        item = runtime_execution_request_continuation_payload(later_request)
        if not item:
            continue
        continuation.append(item)
        later_step_id = _first_text(_runtime_request_value(later_request, "step_id"))
        if later_step_id:
            chain_step_ids.add(later_step_id)
        if _is_verification_request(later_request):
            break

    if (
        _is_ui_mutation_request(request)
        and retry_tool in _UI_OBSERVATION_TOOLS
        and continuation
        and _first_text(continuation[0].get("step_id")) == source_step_id
    ):
        continuation = continuation[1:]
    return continuation


def runtime_execution_request_continuation_payload(
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
) -> dict[str, Any]:
    tool_name = _first_text(
        _runtime_request_value(request, "tool_name"),
        _runtime_request_value(request, "tool"),
    )
    if not tool_name:
        return {}

    payload: dict[str, Any] = {
        "tool": tool_name,
        "input": _mapping(_runtime_request_value(request, "input")),
        "planning_reason": "runtime_execution_deferred_continuation",
        "source_request_id": _first_text(_runtime_request_value(request, "request_id")),
    }
    for key in (
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
        "step_id",
        "capability_id",
        "runtime_doctrine",
        "runtime_stage",
        "runtime_role",
        "policy_reason",
        "risk_level",
    ):
        value = _first_text(_runtime_request_value(request, key))
        if value:
            payload[key] = value
    for key in (
        "approval_required",
        "requires_observation",
        "requires_post_action_verification",
        "continue_to_model",
    ):
        value = bool(_runtime_request_value(request, key))
        if value:
            payload[key] = value
    for key in ("depends_on", "replan_triggers", "replan_signal_ids"):
        values = _string_list(_runtime_request_value(request, key))
        if values:
            payload[key] = values
    for key in (
        "task_todo",
        "followup_target",
        "action_target",
        "observation_evidence",
        "observation_retry",
        "desktop_execution_policy",
        "desktop_execution_route",
        "sandbox_provider",
        "desktop_provider_session",
        "desktop_loop",
        "deferred_input",
        "deferred_context",
    ):
        value = _mapping(_runtime_request_value(request, key))
        if value:
            payload[key] = value
    for key in (
        "task_checkpoints",
        "task_workspace_items",
        "verification_targets",
        "task_verification_targets",
        "deferred_continuation",
    ):
        values = _mapping_list(_runtime_request_value(request, key))
        if values:
            payload[key] = values
    deferred_tool = _first_text(_runtime_request_value(request, "deferred_tool"))
    if deferred_tool:
        payload["deferred_tool"] = deferred_tool
    return {key: value for key, value in payload.items() if value not in ("", [], {})}


def _retry_from_observation_request(
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
    retry: Mapping[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    tool_name = _first_text(
        _runtime_request_value(request, "tool_name"),
        _runtime_request_value(request, "tool"),
    )
    retry_input = _mapping(_runtime_request_value(request, "input"))
    payload = dict(retry)
    payload.update(
        {
            "from_tool": tool_name,
            "tool": tool_name,
            "input": retry_input,
            "reason": reason,
        }
    )
    return {key: value for key, value in payload.items() if value not in ("", [], {})}


def _nearest_ui_observation_request(
    envelope: RuntimeExecutionEnvelopeSnapshot,
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
) -> RuntimeExecutionRequestSnapshot | None:
    requests = list(envelope.requests or [])
    source_index = _request_index(envelope, request)
    if source_index < 0:
        return None
    source_step_id = _first_text(_runtime_request_value(request, "step_id"))
    depends_on = set(_string_list(_runtime_request_value(request, "depends_on")))
    for earlier in reversed(requests[:source_index]):
        if not _is_ui_observation_request(earlier):
            continue
        earlier_step_id = _first_text(_runtime_request_value(earlier, "step_id"))
        if source_step_id and earlier_step_id and earlier_step_id in depends_on:
            return earlier
        if _same_desktop_scope(earlier, request):
            return earlier
    for later in requests[source_index + 1 :]:
        if _is_ui_observation_request(later) and _same_desktop_scope(later, request):
            return later
    return None


def _request_index(
    envelope: RuntimeExecutionEnvelopeSnapshot,
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
) -> int:
    source_request_id = _first_text(_runtime_request_value(request, "request_id"))
    source_step_id = _first_text(_runtime_request_value(request, "step_id"))
    for index, candidate in enumerate(envelope.requests or []):
        candidate_request_id = _first_text(_runtime_request_value(candidate, "request_id"))
        if source_request_id and candidate_request_id == source_request_id:
            return index
        candidate_step_id = _first_text(_runtime_request_value(candidate, "step_id"))
        if source_step_id and candidate_step_id == source_step_id:
            return index
    return -1


def _request_continues_chain(
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
    chain_step_ids: set[str],
    continuation: Iterable[Mapping[str, Any]],
) -> bool:
    depends_on = set(_string_list(_runtime_request_value(request, "depends_on")))
    if depends_on and chain_step_ids.intersection(depends_on):
        return True
    if not continuation and not depends_on:
        return _is_ui_mutation_request(request) or _is_verification_request(request)
    return False


def _request_is_completed(request: RuntimeExecutionRequestSnapshot | Mapping[str, Any]) -> bool:
    return _first_text(_runtime_request_value(request, "status")).lower() in _COMPLETED_STATUSES


def _is_ui_observation_request(
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
) -> bool:
    tool_name = _first_text(
        _runtime_request_value(request, "tool_name"),
        _runtime_request_value(request, "tool"),
    )
    if tool_name in _UI_OBSERVATION_TOOLS:
        return True
    action = _first_text(_mapping(_runtime_request_value(request, "action_target")).get("action"))
    role = _first_text(_runtime_request_value(request, "runtime_role"))
    return action == "read_ui" or role in {"inspect_ui", "read_ui"}


def _is_ui_mutation_request(
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
) -> bool:
    tool_name = _first_text(
        _runtime_request_value(request, "tool_name"),
        _runtime_request_value(request, "tool"),
    )
    if tool_name.startswith(("app.", "desktop.")) and any(
        token in tool_name for token in _UI_MUTATION_TOOL_TOKENS
    ):
        return True
    action = _first_text(_mapping(_runtime_request_value(request, "action_target")).get("action"))
    return action in {
        "click_ui",
        "keyboard_key",
        "keyboard_shortcut",
        "scroll_ui",
        "submit_ui",
        "type_ui",
    }


def _is_verification_request(
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
) -> bool:
    return (
        _first_text(_runtime_request_value(request, "runtime_stage")) == "verify"
        or _first_text(_mapping(_runtime_request_value(request, "action_target")).get("action"))
        == "verify_after_action"
    )


def _same_desktop_scope(
    left: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
    right: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
) -> bool:
    left_scope = _scope_signature(left)
    right_scope = _scope_signature(right)
    if left_scope and right_scope:
        return left_scope == right_scope
    return True


def _scope_signature(
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
) -> tuple[str, str, str]:
    target = _mapping(_runtime_request_value(request, "action_target"))
    evidence = _mapping(_runtime_request_value(request, "observation_evidence"))
    inputs = _mapping(_runtime_request_value(request, "input"))
    return (
        _first_text(target.get("app_name"), evidence.get("app_name"), inputs.get("app_name")),
        _first_text(target.get("query"), evidence.get("query"), inputs.get("query")),
        _first_text(
            target.get("selection_source"),
            evidence.get("selection_source"),
            inputs.get("selection_source"),
        ),
    )


def _request_deferred_context(
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
) -> dict[str, Any]:
    context = _mapping(_runtime_request_value(request, "deferred_context"))
    for key in (
        "step_id",
        "capability_id",
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "intent_kind",
        "runtime_stage",
        "runtime_role",
    ):
        value = _first_text(_runtime_request_value(request, key))
        if value and key not in context:
            context[key] = value
    for key in (
        "task_todo",
        "task_checkpoints",
        "task_workspace_items",
        "task_verification_targets",
    ):
        value = _runtime_request_value(request, key)
        if value not in (None, "", [], {}) and key not in context:
            context[key] = value
    return context


def _extend_unique_continuations(
    target: list[dict[str, Any]],
    values: Iterable[Mapping[str, Any]],
) -> None:
    seen = {_continuation_signature(item) for item in target}
    for value in values:
        item = dict(value)
        signature = _continuation_signature(item)
        if signature in seen:
            continue
        seen.add(signature)
        target.append(item)


def _continuation_signature(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _first_text(value.get("tool"), value.get("tool_name")),
        _first_text(value.get("step_id")),
        repr(sorted(_mapping(value.get("input")).items())),
    )


def _runtime_request_value(
    request: RuntimeExecutionRequestSnapshot | Mapping[str, Any],
    key: str,
) -> Any:
    if isinstance(request, Mapping):
        return request.get(key)
    return getattr(request, key, None)


def _mapping(value: Any) -> dict[str, Any]:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            value = model_dump(mode="json", exclude_none=True)
        except TypeError:
            value = model_dump()
    if not isinstance(value, Mapping):
        return {}
    return dict(value)


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value if isinstance(item, Mapping)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_first_text(item) for item in value if _first_text(item)]


def _first_text(*values: Any) -> str:
    for value in values:
        clean = str(value or "").strip()
        if clean:
            return clean
    return ""
