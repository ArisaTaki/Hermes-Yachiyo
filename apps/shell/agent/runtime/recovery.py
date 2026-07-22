"""Pure, capability-driven recovery planning for canonical tool outcomes.

This module deliberately stops at planning.  It never invokes an executor,
requests user input, or mutates runtime state; callers decide how an accepted
plan is materialized at the capability adapter seam.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol

from apps.shell.agent.runtime.tool_outcomes import OutcomeStatus, ToolOutcome

_AUTOMATIC_RECOVERY_STATUSES = frozenset({OutcomeStatus.FAILED, OutcomeStatus.PARTIAL})
_JSON_SCALAR_TYPES = (str, int, float, bool, type(None))


def _canonical_names(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name for value in values if (name := str(value).strip())))


def _freeze_value(value: Any) -> Any:
    """Return a detached, recursively read-only JSON-shaped value."""

    if isinstance(value, _JSON_SCALAR_TYPES):
        return value
    if isinstance(value, Enum):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    raise TypeError(
        "Recovery metadata must contain only mappings, sequences, sets, enums, and scalar values"
    )


def _freeze_metadata(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError("Recovery metadata must be a mapping")
    return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    """An application-agnostic, side-effect-free recovery proposal."""

    strategy_id: str
    action: str
    recovery_hint: str
    required_capabilities: tuple[str, ...]
    source_status: OutcomeStatus
    source_reason: str = ""
    scope_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        strategy_id = str(self.strategy_id).strip()
        action = str(self.action).strip()
        recovery_hint = str(self.recovery_hint).strip()
        required_capabilities = _canonical_names(self.required_capabilities)
        if not strategy_id:
            raise ValueError("RecoveryPlan.strategy_id is required")
        if not action:
            raise ValueError("RecoveryPlan.action is required")
        if not recovery_hint:
            raise ValueError("RecoveryPlan.recovery_hint is required")
        if not required_capabilities:
            raise ValueError("RecoveryPlan requires at least one capability")
        object.__setattr__(self, "strategy_id", strategy_id)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "recovery_hint", recovery_hint)
        object.__setattr__(self, "required_capabilities", required_capabilities)
        object.__setattr__(self, "source_status", OutcomeStatus(self.source_status))
        object.__setattr__(self, "source_reason", str(self.source_reason).strip())
        object.__setattr__(self, "scope_id", str(self.scope_id).strip())
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    @property
    def identity(self) -> tuple[str, str, str, tuple[str, ...], str]:
        """Stable loop-prevention identity, intentionally excluding metadata."""

        return (
            self.strategy_id,
            self.action,
            self.recovery_hint,
            self.required_capabilities,
            self.scope_id,
        )


@dataclass(frozen=True, slots=True)
class RecoveryContext:
    """Immutable facts available to recovery strategies for one decision."""

    outcome: ToolOutcome
    available_capabilities: frozenset[str] = field(default_factory=frozenset)
    attempt_lineage: tuple[RecoveryPlan, ...] = ()
    scope_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ToolOutcome):
            raise TypeError("RecoveryContext.outcome must be a ToolOutcome")
        lineage = tuple(self.attempt_lineage)
        if any(not isinstance(plan, RecoveryPlan) for plan in lineage):
            raise TypeError("RecoveryContext.attempt_lineage must contain RecoveryPlan values")
        object.__setattr__(
            self,
            "available_capabilities",
            frozenset(_canonical_names(self.available_capabilities)),
        )
        object.__setattr__(self, "attempt_lineage", lineage)
        object.__setattr__(self, "scope_id", str(self.scope_id).strip())
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    @property
    def total_attempts(self) -> int:
        return len(self.attempt_lineage)

    def attempts_for(self, strategy_id: str, *, scope_id: str | None = None) -> int:
        canonical_id = str(strategy_id).strip()
        canonical_scope = self.scope_id if scope_id is None else str(scope_id).strip()
        return sum(
            1
            for plan in self.attempt_lineage
            if plan.strategy_id == canonical_id and plan.scope_id == canonical_scope
        )


class RecoveryStrategy(Protocol):
    """Pure strategy seam used by :class:`RecoveryCoordinator`."""

    strategy_id: str
    priority: int

    def propose(self, context: RecoveryContext) -> RecoveryPlan | None:
        """Return a deterministic plan from context facts, without side effects."""


@dataclass(frozen=True, slots=True)
class CapabilityRecoveryStrategy:
    """Declarative adapter from outcome facts to a capability-level action."""

    strategy_id: str
    action: str
    trigger_capabilities: tuple[str, ...]
    trigger_hints: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    statuses: tuple[OutcomeStatus, ...] = (
        OutcomeStatus.FAILED,
        OutcomeStatus.PARTIAL,
    )
    priority: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        strategy_id = str(self.strategy_id).strip()
        action = str(self.action).strip()
        trigger_capabilities = _canonical_names(self.trigger_capabilities)
        trigger_hints = _canonical_names(self.trigger_hints)
        required_capabilities = _canonical_names(self.required_capabilities)
        statuses = tuple(dict.fromkeys(OutcomeStatus(status) for status in self.statuses))
        if not strategy_id:
            raise ValueError("CapabilityRecoveryStrategy.strategy_id is required")
        if not action:
            raise ValueError("CapabilityRecoveryStrategy.action is required")
        if not trigger_capabilities:
            raise ValueError("A recovery strategy requires trigger capabilities")
        if not trigger_hints:
            raise ValueError("A recovery strategy requires trigger hints")
        if not required_capabilities:
            raise ValueError("A recovery strategy requires execution capabilities")
        if not statuses:
            raise ValueError("A recovery strategy requires outcome statuses")
        object.__setattr__(self, "strategy_id", strategy_id)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "trigger_capabilities", trigger_capabilities)
        object.__setattr__(self, "trigger_hints", trigger_hints)
        object.__setattr__(self, "required_capabilities", required_capabilities)
        object.__setattr__(self, "statuses", statuses)
        object.__setattr__(self, "priority", int(self.priority))
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    def propose(self, context: RecoveryContext) -> RecoveryPlan | None:
        outcome = context.outcome
        if outcome.status not in self.statuses or not outcome.retryable:
            return None
        if not set(self.trigger_capabilities).issubset(outcome.capabilities):
            return None
        accepted_hints = set(self.trigger_hints)
        recovery_hint = next(
            (hint for hint in outcome.recovery_hints if hint in accepted_hints),
            "",
        )
        if not recovery_hint:
            return None
        return RecoveryPlan(
            strategy_id=self.strategy_id,
            action=self.action,
            recovery_hint=recovery_hint,
            required_capabilities=self.required_capabilities,
            source_status=outcome.status,
            source_reason=outcome.reason,
            scope_id=context.scope_id,
            metadata=self.metadata,
        )


class RecoveryCoordinator:
    """Select one safe automatic plan without executing it."""

    def __init__(
        self,
        strategies: Iterable[RecoveryStrategy],
        *,
        known_capabilities: Iterable[str],
        max_total_attempts: int = 3,
        max_attempts_per_strategy: int = 1,
    ) -> None:
        registered = tuple(strategies)
        strategy_ids = tuple(str(strategy.strategy_id).strip() for strategy in registered)
        if any(not strategy_id for strategy_id in strategy_ids):
            raise ValueError("Every recovery strategy requires a strategy_id")
        if len(set(strategy_ids)) != len(strategy_ids):
            raise ValueError("Recovery strategy_id values must be unique")
        if max_total_attempts < 0 or max_attempts_per_strategy < 0:
            raise ValueError("Recovery attempt budgets cannot be negative")
        self._strategies = tuple(
            strategy
            for _, strategy in sorted(
                enumerate(registered),
                key=lambda item: (-int(item[1].priority), item[0]),
            )
        )
        self._known_capabilities = frozenset(_canonical_names(known_capabilities))
        self._max_total_attempts = int(max_total_attempts)
        self._max_attempts_per_strategy = int(max_attempts_per_strategy)

    @property
    def known_capabilities(self) -> frozenset[str]:
        return self._known_capabilities

    def plan(self, context: RecoveryContext) -> RecoveryPlan | None:
        """Return the highest-priority admissible plan, or ``None``."""

        if not isinstance(context, RecoveryContext):
            raise TypeError("RecoveryCoordinator.plan requires a RecoveryContext")
        outcome = context.outcome
        if outcome.status not in _AUTOMATIC_RECOVERY_STATUSES:
            return None
        if not outcome.retryable or not outcome.capabilities or not outcome.recovery_hints:
            return None
        if context.total_attempts >= self._max_total_attempts:
            return None

        attempted_identities = {plan.identity for plan in context.attempt_lineage}
        for strategy in self._strategies:
            strategy_id = str(strategy.strategy_id).strip()
            if context.attempts_for(strategy_id) >= self._max_attempts_per_strategy:
                continue
            proposal = strategy.propose(context)
            if not isinstance(proposal, RecoveryPlan):
                continue
            if proposal.strategy_id != strategy_id:
                continue
            if proposal.source_status != outcome.status:
                continue
            if proposal.source_reason != outcome.reason:
                continue
            if proposal.scope_id != context.scope_id:
                continue
            if proposal.recovery_hint not in outcome.recovery_hints:
                continue
            required = set(proposal.required_capabilities)
            if not required.issubset(self._known_capabilities):
                continue
            if not required.issubset(context.available_capabilities):
                continue
            if proposal.identity in attempted_identities:
                continue
            return proposal
        return None


__all__ = [
    "CapabilityRecoveryStrategy",
    "RecoveryContext",
    "RecoveryCoordinator",
    "RecoveryPlan",
    "RecoveryStrategy",
]
