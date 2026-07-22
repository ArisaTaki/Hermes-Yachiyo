"""Application-agnostic recovery planning regression tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from apps.shell.agent.runtime.recovery import (
    CapabilityRecoveryStrategy,
    RecoveryContext,
    RecoveryCoordinator,
    RecoveryPlan,
)
from apps.shell.agent.runtime.tool_outcomes import (
    OutcomeStatus,
    ToolOutcome,
    VerificationStatus,
)


def _outcome(
    *,
    capability: str,
    status: OutcomeStatus = OutcomeStatus.FAILED,
    reason: str,
    retryable: bool = True,
    hints: tuple[str, ...],
) -> ToolOutcome:
    return ToolOutcome(
        tool_name="provider-owned-operation",
        capabilities=(capability,),
        status=status,
        reason=reason,
        retryable=retryable,
        effects=(),
        verification=VerificationStatus.NOT_REQUIRED,
        user_action=None,
        recovery_hints=hints,
        provenance=MappingProxyType({}),
        raw={"provider": "opaque"},
    )


def _coordinator() -> RecoveryCoordinator:
    return RecoveryCoordinator(
        (
            CapabilityRecoveryStrategy(
                strategy_id="resolve-entity-alias",
                action="resolve_entity_alias",
                trigger_capabilities=("media.playback",),
                trigger_hints=("entity_not_found",),
                required_capabilities=("knowledge.entity_resolution",),
                priority=20,
            ),
            CapabilityRecoveryStrategy(
                strategy_id="resolve-path-alias",
                action="resolve_path_alias",
                trigger_capabilities=("files.read",),
                trigger_hints=("path_not_found",),
                required_capabilities=("files.path_resolution",),
                priority=10,
            ),
            CapabilityRecoveryStrategy(
                strategy_id="request-authorization",
                action="request_authorization",
                trigger_capabilities=("protected.operation",),
                trigger_hints=("authorization_required",),
                required_capabilities=("authorization.request",),
                statuses=(OutcomeStatus.ACTION_REQUIRED,),
                priority=100,
            ),
        ),
        known_capabilities=(
            "knowledge.entity_resolution",
            "files.path_resolution",
            "authorization.request",
        ),
    )


def test_one_coordinator_reuses_the_same_loop_across_capability_domains() -> None:
    coordinator = _coordinator()

    media_plan = coordinator.plan(
        RecoveryContext(
            outcome=_outcome(
                capability="media.playback",
                reason="catalog_miss",
                hints=("entity_not_found",),
            ),
            available_capabilities=frozenset({"knowledge.entity_resolution"}),
        )
    )
    file_plan = coordinator.plan(
        RecoveryContext(
            outcome=_outcome(
                capability="files.read",
                reason="location_missing",
                hints=("path_not_found",),
            ),
            available_capabilities=frozenset({"files.path_resolution"}),
        )
    )

    assert media_plan is not None
    assert media_plan.strategy_id == "resolve-entity-alias"
    assert media_plan.action == "resolve_entity_alias"
    assert media_plan.source_reason == "catalog_miss"
    assert file_plan is not None
    assert file_plan.strategy_id == "resolve-path-alias"
    assert file_plan.action == "resolve_path_alias"
    assert type(coordinator) is RecoveryCoordinator


def test_action_required_never_becomes_an_automatic_recovery_plan() -> None:
    coordinator = _coordinator()
    context = RecoveryContext(
        outcome=_outcome(
            capability="protected.operation",
            status=OutcomeStatus.ACTION_REQUIRED,
            reason="consent_needed",
            hints=("authorization_required",),
        ),
        available_capabilities=frozenset({"authorization.request"}),
    )

    assert coordinator.plan(context) is None


@pytest.mark.parametrize(
    ("status", "retryable"),
    [
        (OutcomeStatus.SUCCESS, True),
        (OutcomeStatus.SKIPPED, True),
        (OutcomeStatus.FAILED, False),
    ],
)
def test_terminal_or_nonretryable_outcomes_are_not_planned(
    status: OutcomeStatus,
    retryable: bool,
) -> None:
    context = RecoveryContext(
        outcome=_outcome(
            capability="media.playback",
            status=status,
            reason="terminal",
            retryable=retryable,
            hints=("entity_not_found",),
        ),
        available_capabilities=frozenset({"knowledge.entity_resolution"}),
    )

    assert _coordinator().plan(context) is None


def test_strategy_requires_both_matching_hint_and_outcome_capability() -> None:
    coordinator = _coordinator()
    wrong_hint = RecoveryContext(
        outcome=_outcome(
            capability="media.playback",
            reason="miss",
            hints=("path_not_found",),
        ),
        available_capabilities=frozenset({"knowledge.entity_resolution"}),
    )
    wrong_capability = RecoveryContext(
        outcome=_outcome(
            capability="files.read",
            reason="miss",
            hints=("entity_not_found",),
        ),
        available_capabilities=frozenset({"knowledge.entity_resolution"}),
    )

    assert coordinator.plan(wrong_hint) is None
    assert coordinator.plan(wrong_capability) is None


@pytest.mark.parametrize(
    ("known_capabilities", "available_capabilities"),
    [
        (("fallback.resolve",), ("fallback.resolve",)),
        (("unknown.resolve", "fallback.resolve"), ("fallback.resolve",)),
    ],
)
def test_unknown_or_unavailable_capability_plan_is_rejected_and_falls_through(
    known_capabilities: tuple[str, ...],
    available_capabilities: tuple[str, ...],
) -> None:
    coordinator = RecoveryCoordinator(
        (
            CapabilityRecoveryStrategy(
                strategy_id="invalid-first-choice",
                action="resolve_with_unavailable_capability",
                trigger_capabilities=("records.lookup",),
                trigger_hints=("entity_not_found",),
                required_capabilities=("unknown.resolve",),
                priority=100,
            ),
            CapabilityRecoveryStrategy(
                strategy_id="valid-fallback",
                action="resolve_with_fallback",
                trigger_capabilities=("records.lookup",),
                trigger_hints=("entity_not_found",),
                required_capabilities=("fallback.resolve",),
            ),
        ),
        known_capabilities=known_capabilities,
    )
    context = RecoveryContext(
        outcome=_outcome(
            capability="records.lookup",
            reason="missing",
            hints=("entity_not_found",),
        ),
        available_capabilities=frozenset(available_capabilities),
    )

    plan = coordinator.plan(context)

    assert plan is not None
    assert plan.strategy_id == "valid-fallback"


def test_duplicate_registered_strategy_id_is_rejected() -> None:
    strategy = CapabilityRecoveryStrategy(
        strategy_id="same-id",
        action="resolve",
        trigger_capabilities=("records.lookup",),
        trigger_hints=("entity_not_found",),
        required_capabilities=("records.resolve",),
    )

    with pytest.raises(ValueError, match="unique"):
        RecoveryCoordinator(
            (strategy, strategy),
            known_capabilities=("records.resolve",),
        )


def test_attempt_lineage_rejects_an_identical_plan_even_with_budget_remaining() -> None:
    coordinator = RecoveryCoordinator(
        (
            CapabilityRecoveryStrategy(
                strategy_id="bounded-resolver",
                action="resolve",
                trigger_capabilities=("records.lookup",),
                trigger_hints=("entity_not_found",),
                required_capabilities=("records.resolve",),
            ),
        ),
        known_capabilities=("records.resolve",),
        max_total_attempts=5,
        max_attempts_per_strategy=3,
    )
    outcome = _outcome(
        capability="records.lookup",
        reason="missing",
        hints=("entity_not_found",),
    )
    first_plan = coordinator.plan(
        RecoveryContext(
            outcome=outcome,
            available_capabilities=frozenset({"records.resolve"}),
        )
    )
    assert first_plan is not None

    repeated = coordinator.plan(
        RecoveryContext(
            outcome=outcome,
            available_capabilities=frozenset({"records.resolve"}),
            attempt_lineage=(first_plan,),
        )
    )

    assert repeated is None


def test_total_and_per_strategy_attempt_budgets_are_independent() -> None:
    strategy = CapabilityRecoveryStrategy(
        strategy_id="bounded-resolver",
        action="current_action",
        trigger_capabilities=("records.lookup",),
        trigger_hints=("entity_not_found",),
        required_capabilities=("records.resolve",),
    )
    outcome = _outcome(
        capability="records.lookup",
        reason="missing",
        hints=("entity_not_found",),
    )
    prior_other_strategy = RecoveryPlan(
        strategy_id="other-strategy",
        action="prior_action",
        recovery_hint="entity_not_found",
        required_capabilities=("records.resolve",),
        source_status=OutcomeStatus.FAILED,
        source_reason="missing",
    )
    prior_same_strategy_different_plan = RecoveryPlan(
        strategy_id="bounded-resolver",
        action="prior_action",
        recovery_hint="entity_not_found",
        required_capabilities=("records.resolve",),
        source_status=OutcomeStatus.FAILED,
        source_reason="missing",
    )

    total_limited = RecoveryCoordinator(
        (strategy,),
        known_capabilities=("records.resolve",),
        max_total_attempts=1,
        max_attempts_per_strategy=5,
    )
    per_strategy_limited = RecoveryCoordinator(
        (strategy,),
        known_capabilities=("records.resolve",),
        max_total_attempts=5,
        max_attempts_per_strategy=1,
    )

    assert (
        total_limited.plan(
            RecoveryContext(
                outcome=outcome,
                available_capabilities=frozenset({"records.resolve"}),
                attempt_lineage=(prior_other_strategy,),
            )
        )
        is None
    )
    assert (
        per_strategy_limited.plan(
            RecoveryContext(
                outcome=outcome,
                available_capabilities=frozenset({"records.resolve"}),
                attempt_lineage=(prior_same_strategy_different_plan,),
            )
        )
        is None
    )


def test_per_strategy_budget_is_scoped_but_total_budget_spans_the_run() -> None:
    coordinator = RecoveryCoordinator(
        (
            CapabilityRecoveryStrategy(
                strategy_id="bounded-resolver",
                action="resolve",
                trigger_capabilities=("records.lookup",),
                trigger_hints=("entity_not_found",),
                required_capabilities=("records.resolve",),
            ),
        ),
        known_capabilities=("records.resolve",),
        max_total_attempts=2,
        max_attempts_per_strategy=1,
    )
    outcome = _outcome(
        capability="records.lookup",
        reason="missing",
        hints=("entity_not_found",),
    )
    first = coordinator.plan(
        RecoveryContext(
            outcome=outcome,
            available_capabilities=frozenset({"records.resolve"}),
            scope_id="step-a",
        )
    )
    assert first is not None
    assert first.scope_id == "step-a"

    assert (
        coordinator.plan(
            RecoveryContext(
                outcome=outcome,
                available_capabilities=frozenset({"records.resolve"}),
                attempt_lineage=(first,),
                scope_id="step-a",
            )
        )
        is None
    )

    second = coordinator.plan(
        RecoveryContext(
            outcome=outcome,
            available_capabilities=frozenset({"records.resolve"}),
            attempt_lineage=(first,),
            scope_id="step-b",
        )
    )
    assert second is not None
    assert second.scope_id == "step-b"

    assert (
        coordinator.plan(
            RecoveryContext(
                outcome=outcome,
                available_capabilities=frozenset({"records.resolve"}),
                attempt_lineage=(first, second),
                scope_id="step-c",
            )
        )
        is None
    )


def test_context_and_plan_are_immutable_and_defensively_freeze_metadata() -> None:
    context_source: dict[str, Any] = {
        "nested": {"values": ["original"]},
    }
    plan_source: dict[str, Any] = {
        "audit": {"labels": ["safe"]},
    }
    context = RecoveryContext(
        outcome=_outcome(
            capability="records.lookup",
            reason="missing",
            hints=("entity_not_found",),
        ),
        metadata=context_source,
    )
    plan = RecoveryPlan(
        strategy_id="immutable",
        action="resolve",
        recovery_hint="entity_not_found",
        required_capabilities=("records.resolve",),
        source_status=OutcomeStatus.FAILED,
        metadata=plan_source,
    )
    context_source["nested"]["values"].append("mutated")
    plan_source["audit"]["labels"].append("mutated")

    assert context.metadata["nested"]["values"] == ("original",)
    assert plan.metadata["audit"]["labels"] == ("safe",)
    with pytest.raises(TypeError):
        context.metadata["new"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        plan.metadata["audit"]["new"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        plan.action = "changed"  # type: ignore[misc]


def test_core_recovery_module_contains_no_product_or_concrete_operation_names() -> None:
    source = Path("apps/shell/agent/runtime/recovery.py").read_text(encoding="utf-8").lower()

    for forbidden in (
        "apple music",
        "media.apple_music",
        "browser.search",
        "spotify",
        "finder",
    ):
        assert forbidden not in source
