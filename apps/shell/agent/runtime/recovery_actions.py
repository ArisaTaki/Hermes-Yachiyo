"""Execution seam for bounded, capability-planned recovery actions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from apps.shell.agent.runtime.recovery import RecoveryPlan
from apps.shell.agent.runtime.tool_outcomes import ToolOutcome


def _canonical_names(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name for value in values if (name := str(value or "").strip())))


@dataclass(frozen=True, slots=True)
class RecoveryActionScope:
    """Public execution bounds visible to an action adapter."""

    allowed_tools: frozenset[str]
    iteration: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_tools",
            frozenset(_canonical_names(self.allowed_tools)),
        )
        object.__setattr__(self, "iteration", max(0, int(self.iteration)))

    @property
    def next_iteration(self) -> int:
        return self.iteration + 1

    def allows_all(self, tool_names: Iterable[str]) -> bool:
        return set(_canonical_names(tool_names)).issubset(self.allowed_tools)


@dataclass(frozen=True, slots=True)
class RecoveryToolResult:
    """One result correlated to the internal request that produced it."""

    tool_call_id: str
    result: Any
    event_type: str = ""

    @property
    def failed(self) -> bool:
        return self.event_type == "agent.tool.failed"


@dataclass(frozen=True, slots=True)
class RecoveryToolBatch:
    """An internal tool batch plus an opaque completion-projection token."""

    requests: tuple[Mapping[str, Any], ...]
    results: tuple[RecoveryToolResult, ...]
    completion_token: Any = None

    def tool_result_for(self, tool_call_id: str) -> RecoveryToolResult | None:
        expected = str(tool_call_id or "").strip()
        for item in reversed(self.results):
            if item.tool_call_id == expected:
                return item
        return None

    def result_for(self, tool_call_id: str) -> Any:
        matched = self.tool_result_for(tool_call_id)
        return matched.result if matched is not None else None


class RecoveryActionDisposition(str, Enum):
    """Typed intent produced by one bounded recovery action attempt."""

    TERMINAL_COMPLETION = "terminal_completion"
    CONTINUE_PLAN = "continue_plan"
    AWAIT_USER = "await_user"
    NOT_HANDLED = "not_handled"
    EXECUTION_FAILED = "execution_failed"


class RecoveryActionExecutionMode(str, Enum):
    """Maximum side-effect authority required by one recovery adapter.

    Adapters are Runtime-owned code, but they still run below the canonical
    Goal loop.  The mode admits bounded observations and one explicitly typed,
    lineage-bound effect while keeping ordinary retries under the main
    planner/executor authority.
    """

    OBSERVATION_ONLY = "observation_only"
    GOAL_BOUNDED_EFFECTFUL = "goal_bounded_effectful"
    EFFECTFUL = "effectful"


@dataclass(frozen=True, slots=True)
class RecoveryActionResult:
    """Outcome and next-loop intent of one recovery action attempt."""

    disposition: RecoveryActionDisposition
    terminal_output: str = ""
    reason: str = ""
    attempts: tuple[RecoveryToolBatch, ...] = ()

    def __post_init__(self) -> None:
        output = (
            self.terminal_output
            if isinstance(self.terminal_output, str)
            else str(self.terminal_output or "")
        )
        object.__setattr__(self, "terminal_output", output)
        object.__setattr__(self, "reason", str(self.reason or "").strip())
        object.__setattr__(self, "attempts", tuple(self.attempts))
        if (
            self.disposition is RecoveryActionDisposition.TERMINAL_COMPLETION
            and not output.strip()
        ):
            raise ValueError("terminal completion requires terminal output")

    @classmethod
    def complete(
        cls,
        terminal_output: str,
        *,
        attempts: Iterable[RecoveryToolBatch] = (),
    ) -> RecoveryActionResult:
        return cls(
            disposition=RecoveryActionDisposition.TERMINAL_COMPLETION,
            terminal_output=(
                terminal_output
                if isinstance(terminal_output, str)
                else str(terminal_output or "")
            ),
            attempts=tuple(attempts),
        )

    @classmethod
    def continue_plan(
        cls,
        *,
        reason: str = "",
        attempts: Iterable[RecoveryToolBatch] = (),
    ) -> RecoveryActionResult:
        return cls(
            disposition=RecoveryActionDisposition.CONTINUE_PLAN,
            reason=str(reason or "").strip(),
            attempts=tuple(attempts),
        )

    @classmethod
    def await_user(
        cls,
        *,
        reason: str,
        attempts: Iterable[RecoveryToolBatch] = (),
    ) -> RecoveryActionResult:
        return cls(
            disposition=RecoveryActionDisposition.AWAIT_USER,
            reason=str(reason or "").strip(),
            attempts=tuple(attempts),
        )

    @classmethod
    def not_handled(cls, *, reason: str = "") -> RecoveryActionResult:
        return cls(
            disposition=RecoveryActionDisposition.NOT_HANDLED,
            reason=str(reason or "").strip(),
        )

    @classmethod
    def failed(
        cls,
        *,
        reason: str,
        attempts: Iterable[RecoveryToolBatch] = (),
    ) -> RecoveryActionResult:
        return cls(
            disposition=RecoveryActionDisposition.EXECUTION_FAILED,
            reason=str(reason or "").strip(),
            attempts=tuple(attempts),
        )


@dataclass(frozen=True, slots=True)
class RecoveryModelTurn:
    """Model-selected requests without exposing model credentials or budget state."""

    message: Mapping[str, Any]
    visible_content: str
    tool_requests: tuple[Mapping[str, Any], ...]


class RecoveryRuntimePort(Protocol):
    """High-depth runtime operations available to recovery adapters."""

    def execute_tools(
        self,
        tool_requests: Sequence[Mapping[str, Any]],
        *,
        allowed_tools: Iterable[str],
        next_iteration: int,
    ) -> RecoveryToolBatch:
        """Execute a bounded internal batch under a narrowed allowlist."""

    def select_tool(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        allowed_tools: Iterable[str],
    ) -> RecoveryModelTurn:
        """Run one budgeted model turn that may select a tool."""

    def commit_model_turn(
        self,
        *,
        user_prompt: str,
        turn: RecoveryModelTurn,
    ) -> None:
        """Commit an accepted model turn to the canonical message protocol."""

    def project_completion(self, batch: RecoveryToolBatch) -> str:
        """Project a tool batch through the existing terminal result path."""

    def release_owned_resources(self) -> None:
        """Release resources owned by this recovery attempt, at most once."""


@dataclass(frozen=True, slots=True)
class RecoveryActionContext:
    """Correlated source facts and bounded runtime access for one action."""

    plan: RecoveryPlan
    source_outcome: ToolOutcome
    source_tool_call_id: str
    scope: RecoveryActionScope
    runtime: RecoveryRuntimePort

    def __post_init__(self) -> None:
        if not isinstance(self.plan, RecoveryPlan):
            raise TypeError("RecoveryActionContext.plan must be a RecoveryPlan")
        if not isinstance(self.source_outcome, ToolOutcome):
            raise TypeError("RecoveryActionContext.source_outcome must be a ToolOutcome")
        if not isinstance(self.scope, RecoveryActionScope):
            raise TypeError("RecoveryActionContext.scope must be a RecoveryActionScope")
        if self.plan.source_status != self.source_outcome.status:
            raise ValueError("Recovery plan status does not match its source outcome")
        if self.plan.source_reason != self.source_outcome.reason:
            raise ValueError("Recovery plan reason does not match its source outcome")
        object.__setattr__(
            self,
            "source_tool_call_id",
            str(self.source_tool_call_id or "").strip(),
        )


class RecoveryActionAdapter(Protocol):
    """Application adapter for one capability-level recovery action."""

    action: str
    execution_mode: RecoveryActionExecutionMode

    def supports(self, context: RecoveryActionContext) -> bool:
        """Return whether this adapter uniquely owns the correlated context."""

    def execute(self, context: RecoveryActionContext) -> RecoveryActionResult:
        """Execute one action attempt. Exceptions intentionally propagate."""


class ResolvedRecoveryAction:
    """Single-use result of a unique registry resolution."""

    def __init__(
        self,
        *,
        adapter: RecoveryActionAdapter,
        context: RecoveryActionContext,
    ) -> None:
        self._adapter = adapter
        self._context = context
        self._executed = False
        raw_execution_mode = getattr(
            adapter,
            "execution_mode",
            RecoveryActionExecutionMode.EFFECTFUL,
        )
        try:
            self._execution_mode = RecoveryActionExecutionMode(raw_execution_mode)
        except ValueError as exc:
            raise ValueError(
                "Recovery action adapter execution_mode must be observation_only, "
                "goal_bounded_effectful, or effectful"
            ) from exc

    @property
    def context(self) -> RecoveryActionContext:
        return self._context

    @property
    def execution_mode(self) -> RecoveryActionExecutionMode:
        """Return the adapter's declared maximum execution authority.

        Legacy adapters without a declaration fail closed as effectful.
        """

        return self._execution_mode

    @property
    def adapter_type(self) -> type[Any]:
        """Return the exact Runtime-owned adapter type selected by the registry."""

        return type(self._adapter)

    def execute(self) -> RecoveryActionResult:
        if self._executed:
            return RecoveryActionResult.not_handled(reason="already_executed")
        self._executed = True
        result = self._adapter.execute(self._context)
        if isinstance(result, RecoveryActionResult):
            return result
        if isinstance(result, str):
            if result:
                return RecoveryActionResult.complete(result)
            return RecoveryActionResult.not_handled(reason="legacy_empty_result")
        raise TypeError("Recovery action adapters must return RecoveryActionResult")

    def reconcile_completed_attempt(
        self,
        batch: RecoveryToolBatch,
    ) -> RecoveryActionResult:
        """Interpret a source-correlated attempt already run by a legacy owner."""

        reconcile = getattr(self._adapter, "reconcile_completed_attempt", None)
        if not callable(reconcile):
            return RecoveryActionResult.not_handled(
                reason="completed_attempt_reconciliation_unavailable"
            )
        result = reconcile(self._context, batch)
        if isinstance(result, RecoveryActionResult):
            return result
        raise TypeError(
            "Recovery action attempt reconciliation must return RecoveryActionResult"
        )


class RecoveryActionRegistry:
    """Resolve exactly one supporting adapter, failing closed otherwise."""

    def __init__(self, adapters: Iterable[RecoveryActionAdapter] = ()) -> None:
        self._adapters = tuple(adapters)
        for adapter in self._adapters:
            if not str(getattr(adapter, "action", "") or "").strip():
                raise ValueError("Every recovery action adapter requires an action")

    @property
    def adapters(self) -> tuple[RecoveryActionAdapter, ...]:
        return self._adapters

    def resolve(
        self,
        context: RecoveryActionContext,
    ) -> ResolvedRecoveryAction | None:
        if not isinstance(context, RecoveryActionContext):
            raise TypeError("RecoveryActionRegistry requires a RecoveryActionContext")
        matches = tuple(
            adapter
            for adapter in self._adapters
            if str(adapter.action).strip() == context.plan.action and adapter.supports(context)
        )
        if len(matches) != 1:
            return None
        return ResolvedRecoveryAction(adapter=matches[0], context=context)

    def execute(self, context: RecoveryActionContext) -> RecoveryActionResult:
        resolved = self.resolve(context)
        if resolved is None:
            return RecoveryActionResult.not_handled(reason="no_unique_adapter")
        return resolved.execute()


__all__ = [
    "RecoveryActionAdapter",
    "RecoveryActionContext",
    "RecoveryActionDisposition",
    "RecoveryActionExecutionMode",
    "RecoveryActionRegistry",
    "RecoveryActionResult",
    "RecoveryActionScope",
    "RecoveryModelTurn",
    "RecoveryRuntimePort",
    "RecoveryToolBatch",
    "RecoveryToolResult",
    "ResolvedRecoveryAction",
]
