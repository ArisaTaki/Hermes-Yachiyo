"""Application-agnostic disposition of one authoritative tool outcome."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from apps.shell.agent.runtime.event_scopes import runtime_event_payload
from apps.shell.agent.runtime.recovery import RecoveryPlan
from apps.shell.agent.runtime.recovery_actions import (
    RecoveryActionDisposition,
    RecoveryActionResult,
)
from apps.shell.agent.runtime.recovery_policies import (
    RecoveryAssessment,
    assess_latest_tool_recovery,
    recovery_attempt_lineage_from_timeline,
)
from apps.shell.agent.runtime.tool_outcomes import OutcomeStatus, ToolOutcome


class OutcomeLoopDisposition(str, Enum):
    """Exactly one next-loop intent after assessing a tool attempt."""

    CONTINUE_PLAN = "continue_plan"
    REPLAN_MODEL = "replan_model"
    AWAIT_USER = "await_user"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


_TERMINAL_TOOL_EVENT_TYPES = frozenset(
    {"agent.tool.call", "agent.tool.failed", "agent.tool.skipped"}
)
_APPROVAL_PENDING_STATUSES = frozenset(
    {"approval_required", "awaiting_approval", "waiting_approval"}
)
_APPROVAL_RESOLUTION_IDENTITY_KEYS = (
    "approval_id",
    "approval_generation_id",
    "approval_claim_id",
    "approval_request_fingerprint",
    "decision_id",
    "plan_id",
    "tool_plan_id",
    "step_id",
    "request_id",
    "materialization_binding_id",
    "materialized_content_sha256",
)


def _trusted_terminal_payload(
    event: Mapping[str, Any],
    *,
    run_id: str,
) -> Mapping[str, Any] | None:
    """Normalize one executor-owned terminal without accepting scope conflicts."""

    nested = event.get("payload")
    nested_payload = nested if isinstance(nested, Mapping) else {}
    payload = runtime_event_payload(event)
    event_types = {
        str(value or "").strip()
        for source in (event, nested_payload)
        for value in (source.get("event"), source.get("event_type"))
        if str(value or "").strip()
    }
    run_ids = {
        str(source.get("run_id") or "").strip()
        for source in (event, nested_payload)
        if str(source.get("run_id") or "").strip()
    }
    actors = {
        str(source.get("actor") or "").strip()
        for source in (event, nested_payload)
        if str(source.get("actor") or "").strip()
    }
    authorities = {
        str(source.get("execution_authority") or "").strip()
        for source in (event, nested_payload)
        if str(source.get("execution_authority") or "").strip()
    }
    tool_call_ids = {
        str(source.get("tool_call_id") or "").strip()
        for source in (event, nested_payload)
        if str(source.get("tool_call_id") or "").strip()
    }
    if (
        len(event_types) != 1
        or not event_types.issubset(_TERMINAL_TOOL_EVENT_TYPES)
        or run_ids != {run_id}
        or actors != {"native_runtime"}
        or authorities != {"runtime_tool_executor"}
        or len(tool_call_ids) != 1
        or not str(payload.get("tool") or payload.get("detail") or "").strip()
        or "result" not in payload
    ):
        return None
    return payload


def _has_approval_pending_markers(payload: Mapping[str, Any]) -> bool:
    """Detect approval-pending facts independently from resolution claims."""

    result = payload.get("result")
    if not isinstance(result, Mapping):
        return False
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    return any(
        source.get("approval_required") is True
        or str(source.get("status") or "").strip().lower()
        in _APPROVAL_PENDING_STATUSES
        for source in (payload, result, data)
    )


def _approval_pending_payload(payload: Mapping[str, Any]) -> bool:
    """Keep an executor-owned approval request outside terminal arbitration."""

    return _has_approval_pending_markers(payload)


def _trusted_approved_terminal_after_pending(
    pending: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> bool:
    """Accept only the canonical executor resolution of one approval pause."""

    if (
        terminal.get("approved") is not True
        or terminal.get("approval_resume_result_canonical") is not True
        or _has_approval_pending_markers(terminal)
    ):
        return False
    pending_tool = str(
        pending.get("tool") or pending.get("detail") or ""
    ).strip()
    terminal_tool = str(
        terminal.get("tool") or terminal.get("detail") or ""
    ).strip()
    if not pending_tool or terminal_tool != pending_tool:
        return False
    for key in _APPROVAL_RESOLUTION_IDENTITY_KEYS:
        pending_value = str(pending.get(key) or "").strip()
        if pending_value and str(terminal.get(key) or "").strip() != pending_value:
            return False
    return True


@dataclass(frozen=True, slots=True)
class OutcomeLoopResult:
    """One authoritative outcome and its single next-loop intent."""

    disposition: OutcomeLoopDisposition
    outcome: ToolOutcome
    recovery_plan: RecoveryPlan | None
    source_tool_call_id: str
    recovery_action_result: RecoveryActionResult | None = None
    terminal_output: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.terminal_output:
            return
        recovery = self.recovery_action_result
        if (
            self.disposition is not OutcomeLoopDisposition.COMPLETED
            or recovery is None
            or recovery.disposition
            is not RecoveryActionDisposition.TERMINAL_COMPLETION
            or self.terminal_output != recovery.terminal_output
        ):
            raise ValueError(
                "terminal output requires a terminal recovery completion"
            )


class OutcomeLoopCoordinator:
    """Map canonical outcome facts to one application-independent loop intent."""

    @staticmethod
    def _result(
        assessment: RecoveryAssessment,
        disposition: OutcomeLoopDisposition,
        recovery_action_result: RecoveryActionResult | None,
        *,
        terminal_output: str = "",
        reason: str = "",
    ) -> OutcomeLoopResult:
        return OutcomeLoopResult(
            disposition=disposition,
            outcome=assessment.outcome,
            recovery_plan=assessment.plan,
            source_tool_call_id=assessment.tool_call_id,
            recovery_action_result=recovery_action_result,
            terminal_output=terminal_output,
            reason=reason,
        )

    def decide(
        self,
        assessment: RecoveryAssessment,
        *,
        recovery_action_result: RecoveryActionResult | None = None,
        remaining_plan: bool = False,
    ) -> OutcomeLoopResult:
        if not isinstance(assessment, RecoveryAssessment):
            raise TypeError("OutcomeLoopCoordinator requires a RecoveryAssessment")
        if recovery_action_result is not None and not isinstance(
            recovery_action_result,
            RecoveryActionResult,
        ):
            raise TypeError("recovery_action_result must be a RecoveryActionResult")

        outcome = assessment.outcome
        if outcome.status is OutcomeStatus.ACTION_REQUIRED:
            # ACTION_REQUIRED is authoritative terminal control flow, not a
            # recoverable failure.  Normalize any stale/contradictory adapter
            # result so direct desktop paths cannot fall through to a model
            # profile lookup after Runtime has already determined that only
            # the user can unblock the operation.
            recovery_action_result = RecoveryActionResult.await_user(
                reason=outcome.reason or "action_required"
            )
            return self._result(
                assessment,
                OutcomeLoopDisposition.AWAIT_USER,
                recovery_action_result,
                reason=outcome.reason,
            )
        completion_impact = (
            str(outcome.raw.get("completion_impact") or "").strip()
            if isinstance(outcome.raw, Mapping)
            else ""
        )
        if (
            outcome.status in {OutcomeStatus.FAILED, OutcomeStatus.SKIPPED}
            and isinstance(outcome.raw, Mapping)
            and (
                outcome.raw.get("blocked_by_user_goal") is True
                or completion_impact in {"continue_without_tool", "report_refusal"}
            )
        ):
            # A rejected tool can still be the correct safe behavior. Return
            # control to the model so it can explain the refusal without
            # claiming that the prohibited side effect happened.
            return self._result(
                assessment,
                OutcomeLoopDisposition.REPLAN_MODEL,
                recovery_action_result,
                reason=completion_impact or "continue_without_tool",
            )
        if (
            recovery_action_result is not None
            and recovery_action_result.disposition
            is RecoveryActionDisposition.AWAIT_USER
        ):
            return self._result(
                assessment,
                OutcomeLoopDisposition.AWAIT_USER,
                recovery_action_result,
                reason=recovery_action_result.reason or outcome.reason,
            )
        if (
            recovery_action_result is not None
            and recovery_action_result.disposition
            is RecoveryActionDisposition.TERMINAL_COMPLETION
        ):
            return self._result(
                assessment,
                OutcomeLoopDisposition.COMPLETED,
                recovery_action_result,
                terminal_output=recovery_action_result.terminal_output,
                reason=recovery_action_result.reason,
            )
        if (
            recovery_action_result is not None
            and recovery_action_result.disposition
            is RecoveryActionDisposition.CONTINUE_PLAN
        ):
            return self._result(
                assessment,
                OutcomeLoopDisposition.CONTINUE_PLAN,
                recovery_action_result,
                reason=recovery_action_result.reason,
            )
        if (
            (
                outcome.status is OutcomeStatus.FAILED
                or (
                    outcome.status is OutcomeStatus.PARTIAL
                    and assessment.plan is not None
                )
            )
            and outcome.retryable
            and recovery_action_result is not None
            and recovery_action_result.disposition
            in {
                RecoveryActionDisposition.EXECUTION_FAILED,
                RecoveryActionDisposition.NOT_HANDLED,
            }
        ):
            return self._result(
                assessment,
                OutcomeLoopDisposition.REPLAN_MODEL,
                recovery_action_result,
                reason=recovery_action_result.reason or outcome.reason,
            )
        if outcome.status is OutcomeStatus.FAILED:
            return self._result(
                assessment,
                (
                    OutcomeLoopDisposition.REPLAN_MODEL
                    if outcome.retryable
                    else OutcomeLoopDisposition.FAILED
                ),
                recovery_action_result,
                reason=outcome.reason,
            )
        if outcome.status is OutcomeStatus.SUCCESS:
            return self._result(
                assessment,
                (
                    OutcomeLoopDisposition.CONTINUE_PLAN
                    if remaining_plan
                    else OutcomeLoopDisposition.COMPLETED
                ),
                recovery_action_result,
                reason=outcome.reason,
            )
        if outcome.status is OutcomeStatus.PARTIAL:
            return self._result(
                assessment,
                OutcomeLoopDisposition.PARTIAL,
                recovery_action_result,
                reason=outcome.reason,
            )
        if outcome.status is OutcomeStatus.SKIPPED:
            return self._result(
                assessment,
                (
                    OutcomeLoopDisposition.REPLAN_MODEL
                    if outcome.retryable
                    else OutcomeLoopDisposition.FAILED
                ),
                recovery_action_result,
                reason=outcome.reason,
            )
        raise AssertionError(f"unsupported outcome status: {outcome.status!r}")

    def decide_terminal_batch(
        self,
        *,
        timeline: Sequence[Mapping[str, Any]],
        start_index: int,
        run_id: str,
        allowed_tools: Iterable[str],
        planned_tool_call_ids: Sequence[str] = (),
        recovery_action: (
            Callable[[RecoveryAssessment], RecoveryActionResult] | None
        ) = None,
    ) -> tuple[OutcomeLoopResult, ...]:
        """Route each call's first trusted terminal in one batch through ``decide``.

        Terminal identity is scoped to the explicit Runtime run. A later
        compatibility copy or conflicting terminal for the same call cannot
        reassess the outcome or execute recovery again.
        """

        safe_start = max(0, int(start_index or 0))
        clean_run_id = str(run_id or "").strip()
        if not clean_run_id:
            return ()
        planned_ids = tuple(str(value or "").strip() for value in planned_tool_call_ids)
        planned_positions: dict[str, int] = {}
        for index, tool_call_id in enumerate(planned_ids):
            if tool_call_id:
                planned_positions.setdefault(tool_call_id, index)

        terminal_winners: dict[str, int] = {}
        approval_pending_by_call: dict[str, Mapping[str, Any]] = {}
        for event_index in range(safe_start, len(timeline)):
            payload = _trusted_terminal_payload(
                timeline[event_index],
                run_id=clean_run_id,
            )
            if payload is None:
                continue
            tool_call_id = str(payload.get("tool_call_id") or "").strip()
            if _approval_pending_payload(payload):
                approval_pending_by_call.setdefault(tool_call_id, payload)
                continue
            pending = approval_pending_by_call.get(tool_call_id)
            if pending is not None and not _trusted_approved_terminal_after_pending(
                pending,
                payload,
            ):
                continue
            terminal_winners.setdefault(tool_call_id, event_index)

        terminal_event_indices = [
            event_index
            for tool_call_id, event_index in sorted(
                terminal_winners.items(),
                key=lambda item: (
                    (0, planned_positions[item[0]])
                    if item[0] in planned_positions
                    else (1, item[1])
                ),
            )
        ]
        results: list[OutcomeLoopResult] = []
        for event_index in terminal_event_indices:
            assessment = assess_latest_tool_recovery(
                timeline[: event_index + 1],
                start_index=event_index,
                allowed_tools=allowed_tools,
                attempt_lineage=recovery_attempt_lineage_from_timeline(timeline),
            )
            if assessment is None:
                continue
            request_position = planned_positions.get(assessment.tool_call_id)
            remaining_plan = (
                request_position < len(planned_ids) - 1
                if request_position is not None
                else bool(planned_ids)
            )
            recovery_result = RecoveryActionResult.not_handled(
                reason="recovery_plan_unavailable"
            )
            if assessment.plan is not None:
                if not assessment.tool_call_id:
                    recovery_result = RecoveryActionResult.not_handled(
                        reason="source_tool_call_id_missing"
                    )
                elif recovery_action is None:
                    recovery_result = RecoveryActionResult.not_handled(
                        reason="automatic_recovery_unavailable"
                    )
                else:
                    recovery_result = recovery_action(assessment)
            results.append(
                self.decide(
                    assessment,
                    recovery_action_result=recovery_result,
                    remaining_plan=remaining_plan,
                )
            )
        return tuple(results)


__all__ = [
    "OutcomeLoopCoordinator",
    "OutcomeLoopDisposition",
    "OutcomeLoopResult",
]
