"""Bounded Cua background-window materialization recovery."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.cua_background_provider import CUA_BACKGROUND_PROVIDER_KIND
from apps.shell.agent.runtime.recovery_actions import (
    RecoveryActionContext,
    RecoveryActionExecutionMode,
    RecoveryActionResult,
    RecoveryToolBatch,
)
from apps.shell.agent.runtime.recovery_policies import background_window_source
from apps.shell.agent.runtime.tool_outcomes import OutcomeStatus

_ACTION = "materialize_background_window"
_STRATEGY_ID = "materialize-background-window"
_RECOVERY_HINT = "materialize_background_window"
_SOURCE_CAPABILITIES = ("desktop.app_control",)
_REQUIRED_CAPABILITIES = ("desktop.ui_operation", "desktop.app_discovery")
_SHORTCUT_TOOL = "desktop.safe_shortcut"
_OBSERVATION_TOOL = "desktop.read_ui"
_RECOVERY_TOOLS = (_SHORTCUT_TOOL, _OBSERVATION_TOOL)


class BackgroundWindowRecoveryAdapter:
    """Create one owned background window and prove its identity before resuming."""

    action = _ACTION
    execution_mode = RecoveryActionExecutionMode.GOAL_BOUNDED_EFFECTFUL

    def supports(self, context: RecoveryActionContext) -> bool:
        if (
            context.plan.action != self.action
            or context.plan.strategy_id != _STRATEGY_ID
            or context.plan.recovery_hint != _RECOVERY_HINT
            or context.plan.required_capabilities != _REQUIRED_CAPABILITIES
            or not context.plan.scope_id
            or not context.source_tool_call_id
            or not context.scope.allows_all(_RECOVERY_TOOLS)
        ):
            return False
        outcome = context.source_outcome
        return bool(
            outcome.status is OutcomeStatus.FAILED
            and outcome.retryable
            and outcome.capabilities == _SOURCE_CAPABILITIES
            and _RECOVERY_HINT in outcome.recovery_hints
            and background_window_source(outcome) is not None
        )

    def execute(self, context: RecoveryActionContext) -> RecoveryActionResult:
        if not self.supports(context):
            return RecoveryActionResult.not_handled(reason="unsupported_context")
        requests = (
            {
                "protocol": "json_fallback",
                "tool": _SHORTCUT_TOOL,
                "tool_call_id": _scoped_call_id("background-window-shortcut", context),
                "input": {"action": "new_document"},
                **_recovery_request_identity(
                    context,
                    planning_reason="materialize_owned_background_window",
                ),
            },
            {
                "protocol": "json_fallback",
                "tool": _OBSERVATION_TOOL,
                "tool_call_id": _scoped_call_id("background-window-observe", context),
                # Empty input keeps Cua bound to its cached owned PID target.
                "input": {},
                **_recovery_request_identity(
                    context,
                    planning_reason="verify_owned_background_window",
                ),
            },
        )
        batch = context.runtime.execute_tools(
            requests,
            allowed_tools=_RECOVERY_TOOLS,
            next_iteration=context.scope.next_iteration,
        )
        return self.reconcile_completed_attempt(context, batch)

    def reconcile_completed_attempt(
        self,
        context: RecoveryActionContext,
        batch: RecoveryToolBatch,
    ) -> RecoveryActionResult:
        if not self.supports(context):
            return RecoveryActionResult.not_handled(reason="unsupported_context")
        source = background_window_source(context.source_outcome)
        if source is None:
            return RecoveryActionResult.not_handled(reason="source_unavailable")
        shortcut_id = _correlated_request_call_id(
            batch.requests,
            prefix="background-window-shortcut",
            context=context,
            tool_name=_SHORTCUT_TOOL,
            input_payload={"action": "new_document"},
            planning_reason="materialize_owned_background_window",
        )
        observe_id = _correlated_request_call_id(
            batch.requests,
            prefix="background-window-observe",
            context=context,
            tool_name=_OBSERVATION_TOOL,
            input_payload={},
            planning_reason="verify_owned_background_window",
        )
        if (
            len(batch.requests) != 2
            or not shortcut_id
            or not observe_id
            or shortcut_id == observe_id
            or not _has_exact_correlated_results(
                batch,
                (shortcut_id, observe_id),
            )
        ):
            return RecoveryActionResult.not_handled(reason="background_window_attempt_uncorrelated")
        shortcut = batch.tool_result_for(shortcut_id)
        inspection = batch.tool_result_for(observe_id)
        if not _successful_background_result(shortcut):
            return RecoveryActionResult.failed(
                reason="background_window_shortcut_failed", attempts=(batch,)
            )
        if not _proves_owned_window(inspection, source.pid):
            return RecoveryActionResult.failed(
                reason="background_window_observation_mismatch", attempts=(batch,)
            )
        return RecoveryActionResult.continue_plan(
            reason="background_window_materialized", attempts=(batch,)
        )


def _successful_background_result(result: Any) -> bool:
    return bool(
        result is not None
        and not result.failed
        and isinstance(result.result, Mapping)
        and result.result.get("ok") is True
        and _safe_background_transport(result.result)
        and not _foreground_fallback(result.result)
        and result.result.get("action_dispatched") is True
        and result.result.get("delivery_dispatched") is True
        and result.result.get("delivery_verified") is False
        and result.result.get("window_materialization_pending") is True
        and result.result.get("postcondition_verified") is False
        and result.result.get("requires_postcondition_verification") is True
        and not any(
            result.result.get(key) is True
            for key in (
                "verified",
                "verification_passed",
                "goal_completed",
                "completed",
            )
        )
    )


def _proves_owned_window(result: Any, source_pid: int) -> bool:
    if (
        result is None
        or result.failed
        or not isinstance(result.result, Mapping)
        or result.result.get("ok") is not True
        or not _safe_background_transport(result.result)
        or _foreground_fallback(result.result)
    ):
        return False
    payload = result.result
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    pid = _positive_int(data.get("pid", payload.get("pid")))
    window_id = _positive_int(data.get("window_id", payload.get("window_id")))
    return bool(
        pid == source_pid
        and window_id is not None
        and data.get("agent_owned_target", payload.get("agent_owned_target")) is True
        and data.get("target_bound", payload.get("target_bound")) is True
    )


def _safe_background_transport(payload: Mapping[str, Any]) -> bool:
    transport = payload.get("desktop_execution_provider_transport")
    return bool(
        isinstance(transport, Mapping)
        and transport.get("provider_kind") == CUA_BACKGROUND_PROVIDER_KIND
        and transport.get("delivery_mode") == "background"
        and transport.get("foreground_takeover_required") is False
        and transport.get("foreground_takeover_detected") is not True
    )


def _foreground_fallback(payload: Mapping[str, Any]) -> bool:
    return any(
        payload.get(key) is True
        for key in (
            "fallback_used",
            "foreground_fallback",
            "foreground_fallback_used",
            "foreground_takeover_detected",
        )
    )


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _correlated_request_call_id(
    requests: tuple[Mapping[str, Any], ...],
    *,
    prefix: str,
    context: RecoveryActionContext,
    tool_name: str,
    input_payload: Mapping[str, Any],
    planning_reason: str,
) -> str:
    matches = [
        tool_call_id
        for request in requests
        if str(request.get("tool") or "").strip() == tool_name
        and isinstance(request.get("input"), Mapping)
        and dict(request["input"]) == dict(input_payload)
        and _request_identity_metadata_matches(
            request,
            context=context,
            planning_reason=planning_reason,
        )
        and (
            tool_call_id := _stable_scoped_call_id(
                request.get("tool_call_id"),
                prefix=prefix,
                context=context,
            )
        )
    ]
    return matches[0] if len(matches) == 1 else ""


def _request_identity_metadata_matches(
    request: Mapping[str, Any],
    *,
    context: RecoveryActionContext,
    planning_reason: str,
) -> bool:
    expected_identity = {
        "source": "runtime_internal_recovery",
        "planning_reason": planning_reason,
        "recovery_link_kind": "coordinator_action",
        "source_tool_call_id": context.source_tool_call_id,
        "recovery_action": context.plan.action,
        "recovery_scope_id": context.plan.scope_id,
        "replan_recovery_identity": context.plan.scope_id,
    }
    return all(
        str(request.get(key) or "").strip() == expected
        for key, expected in expected_identity.items()
    )


def _recovery_request_identity(
    context: RecoveryActionContext,
    *,
    planning_reason: str,
) -> dict[str, str]:
    return {
        "source": "runtime_internal_recovery",
        "planning_reason": planning_reason,
        "recovery_link_kind": "coordinator_action",
        "source_tool_call_id": context.source_tool_call_id,
        "recovery_action": context.plan.action,
        "recovery_scope_id": context.plan.scope_id,
        "replan_recovery_identity": context.plan.scope_id,
    }


def _stable_scoped_call_id(
    value: Any,
    *,
    prefix: str,
    context: RecoveryActionContext,
) -> str:
    tool_call_id = str(value or "").strip()
    digest = _scoped_call_digest(context)
    leading = f"{prefix}-"
    trailing = f"-{digest}"
    if not tool_call_id.startswith(leading) or not tool_call_id.endswith(trailing):
        return ""
    iteration_text = tool_call_id[len(leading) : -len(trailing)]
    if not iteration_text or any(character not in "0123456789" for character in iteration_text):
        return ""
    if int(iteration_text) > context.scope.iteration:
        return ""
    return tool_call_id


def _has_exact_correlated_results(
    batch: RecoveryToolBatch,
    tool_call_ids: tuple[str, str],
) -> bool:
    result_ids = [str(result.tool_call_id or "").strip() for result in batch.results]
    return bool(
        len(result_ids) == len(tool_call_ids)
        and len(set(result_ids)) == len(result_ids)
        and set(result_ids) == set(tool_call_ids)
    )


def _scoped_call_digest(context: RecoveryActionContext) -> str:
    identity = f"{context.plan.scope_id}\0{context.source_tool_call_id}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _scoped_call_id(prefix: str, context: RecoveryActionContext) -> str:
    return f"{prefix}-{context.scope.iteration}-{_scoped_call_digest(context)}"


__all__ = ["BackgroundWindowRecoveryAdapter"]
