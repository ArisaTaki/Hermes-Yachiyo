"""Read-only workspace discovery after a trusted file-read resolution miss."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from apps.shell.agent.runtime.recovery_actions import (
    RecoveryActionContext,
    RecoveryActionExecutionMode,
    RecoveryActionResult,
    RecoveryToolBatch,
)
from apps.shell.agent.runtime.recovery_policies import file_resolution_source
from apps.shell.agent.runtime.tool_outcomes import OutcomeStatus

_ACTION = "resolve_file_location"
_STRATEGY_ID = "resolve-file-location"
_RECOVERY_HINT = "file_resolution_failed"
_REQUIRED_CAPABILITIES = ("file.workspace_read",)
_DISCOVERY_TOOL = "workspace.list"


class WorkspaceFileResolutionAdapter:
    """List one correlated directory and let the model choose the next step."""

    action = _ACTION
    execution_mode = RecoveryActionExecutionMode.OBSERVATION_ONLY

    def supports(self, context: RecoveryActionContext) -> bool:
        if (
            context.plan.action != self.action
            or context.plan.strategy_id != _STRATEGY_ID
            or context.plan.recovery_hint != _RECOVERY_HINT
            or context.plan.required_capabilities != _REQUIRED_CAPABILITIES
            or not context.plan.scope_id
            or not context.source_tool_call_id
            or not context.scope.allows_all((_DISCOVERY_TOOL,))
        ):
            return False
        outcome = context.source_outcome
        return bool(
            outcome.status is OutcomeStatus.FAILED
            and outcome.retryable
            and outcome.capabilities == _REQUIRED_CAPABILITIES
            and _RECOVERY_HINT in outcome.recovery_hints
            and file_resolution_source(outcome) is not None
        )

    def execute(self, context: RecoveryActionContext) -> RecoveryActionResult:
        if not self.supports(context):
            return RecoveryActionResult.not_handled(reason="unsupported_context")
        source = file_resolution_source(context.source_outcome)
        if source is None:
            return RecoveryActionResult.not_handled(reason="source_unavailable")
        request = {
            "protocol": "json_fallback",
            "tool": _DISCOVERY_TOOL,
            "tool_call_id": _scoped_call_id("file-resolution-list", context),
            "input": {"path": source.listing_path},
            "source": "runtime_internal_recovery",
            "planning_reason": "file_resolution_discovery",
        }
        batch = context.runtime.execute_tools(
            (request,),
            allowed_tools=(_DISCOVERY_TOOL,),
            next_iteration=context.scope.next_iteration,
        )
        return self.reconcile_completed_attempt(context, batch)

    def reconcile_completed_attempt(
        self,
        context: RecoveryActionContext,
        batch: RecoveryToolBatch,
    ) -> RecoveryActionResult:
        """Classify a correlated discovery attempt without executing it again."""

        if not self.supports(context):
            return RecoveryActionResult.not_handled(reason="unsupported_context")
        source = file_resolution_source(context.source_outcome)
        if source is None:
            return RecoveryActionResult.not_handled(reason="source_unavailable")
        matching_requests = [
            request
            for request in batch.requests
            if str(request.get("tool") or "").strip() == _DISCOVERY_TOOL
            and isinstance(request.get("input"), Mapping)
            and str(request["input"].get("path") or "").strip()
            == source.listing_path
        ]
        if len(matching_requests) != 1:
            return RecoveryActionResult.not_handled(
                reason="discovery_attempt_uncorrelated"
            )
        tool_call_id = str(matching_requests[0].get("tool_call_id") or "").strip()
        correlated_result = batch.tool_result_for(tool_call_id)
        discovery_result = correlated_result.result if correlated_result is not None else None
        if (
            correlated_result is None
            or correlated_result.failed
            or not isinstance(discovery_result, Mapping)
            or discovery_result.get("ok") is not True
        ):
            return RecoveryActionResult.failed(
                reason="discovery_tool_failed",
                attempts=(batch,),
            )
        return RecoveryActionResult.continue_plan(
            reason="discovery_completed",
            attempts=(batch,),
        )


def _scoped_call_id(prefix: str, context: RecoveryActionContext) -> str:
    identity = f"{context.plan.scope_id}\0{context.source_tool_call_id}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{context.scope.iteration}-{digest}"


__all__ = ["WorkspaceFileResolutionAdapter"]
