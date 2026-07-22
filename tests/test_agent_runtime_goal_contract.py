"""Behavioral contract tests for application-independent goal completion."""

from __future__ import annotations

import hashlib
from types import MappingProxyType

from apps.shell.agent.runtime.goal_contract import (
    BoundedSubgoal,
    GoalContract,
    GoalCoordinator,
    GoalCriterion,
)
from apps.shell.agent.runtime.tool_outcomes import (
    OutcomeStatus,
    ToolOutcome,
    VerificationStatus,
)


def _successful_playback_outcome() -> ToolOutcome:
    return ToolOutcome(
        tool_name="media.play",
        capabilities=("media.playback",),
        status=OutcomeStatus.SUCCESS,
        reason="request_dispatched",
        retryable=False,
        effects=("media.playback_requested",),
        verification=VerificationStatus.UNVERIFIED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({"provider": "test"}),
        raw={"ok": True},
    )


def _verified_target_outcome(capability: str) -> ToolOutcome:
    return ToolOutcome(
        tool_name="runtime.test",
        capabilities=(capability,),
        status=OutcomeStatus.SUCCESS,
        reason="verified",
        retryable=False,
        effects=(),
        verification=VerificationStatus.VERIFIED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({"provider": "test"}),
        raw={"ok": True, "postcondition_verified": True},
    )


def _target_contract(
    *,
    capability: str,
    step_id: str,
    target: dict,
) -> GoalContract:
    return GoalContract(
        contract_id=f"goal-target:{capability}:{step_id}",
        run_id=f"run-target:{capability}:{step_id}",
        original_goal="Perform the exact planned action",
        criteria=(
            GoalCriterion(
                criterion_id="target",
                description="The exact planned action target is verified",
                effectful=True,
                required_capabilities=(capability,),
                expected={"state": "fulfilled", "target": target},
                source_step_ids=(step_id,),
            ),
        ),
    )


def test_action_target_aliases_require_matching_capability_and_step_semantics() -> None:
    coordinator = GoalCoordinator()
    shortcut = _target_contract(
        capability="desktop.ui_operation",
        step_id="operate-foreground-ui",
        target={
            "kind": "desktop_ui",
            "action": "shortcut",
            "app_name": "Word",
        },
    )
    running_apps = _target_contract(
        capability="desktop.app_discovery",
        step_id="read_running_apps-desktop-state",
        target={
            "kind": "desktop_app",
            "action": "read_running_apps",
        },
    )

    shortcut_result = coordinator.record_tool_outcome(
        shortcut,
        coordinator.initial(shortcut),
        _verified_target_outcome("desktop.ui_operation"),
        run_id=shortcut.run_id,
        source_tool_call_id="shortcut-call",
        source_step_id="operate-foreground-ui",
        observed={
            "state": "fulfilled",
            "target": {
                "kind": "desktop_app",
                "action": "keyboard_shortcut",
                "app_name": "Word",
            },
        },
    )
    running_apps_result = coordinator.record_tool_outcome(
        running_apps,
        coordinator.initial(running_apps),
        _verified_target_outcome("desktop.app_discovery"),
        run_id=running_apps.run_id,
        source_tool_call_id="running-apps-call",
        source_step_id="read_running_apps-desktop-state",
        observed={
            "state": "fulfilled",
            "target": {
                "kind": "desktop_discovery",
                "action": "list_running_apps",
                "selection_source": "desktop.running_apps",
            },
        },
    )

    assert shortcut_result.completed is True
    assert running_apps_result.completed is True


def test_action_target_aliases_never_accept_wrong_app_action_kind_or_capability() -> None:
    coordinator = GoalCoordinator()
    contract = _target_contract(
        capability="desktop.ui_operation",
        step_id="operate-foreground-ui",
        target={
            "kind": "desktop_ui",
            "action": "shortcut",
            "app_name": "Word",
        },
    )
    invalid_targets = (
        {
            "kind": "desktop_app",
            "action": "keyboard_shortcut",
            "app_name": "Excel",
        },
        {
            "kind": "desktop_app",
            "action": "click_ui",
            "app_name": "Word",
        },
        {
            "kind": "workspace_file",
            "action": "keyboard_shortcut",
            "app_name": "Word",
        },
    )
    for index, target in enumerate(invalid_targets):
        assessment = coordinator.record_tool_outcome(
            contract,
            coordinator.initial(contract),
            _verified_target_outcome("desktop.ui_operation"),
            run_id=contract.run_id,
            source_tool_call_id=f"invalid-{index}",
            source_step_id="operate-foreground-ui",
            observed={"state": "fulfilled", "target": target},
        )
        assert assessment.completed is False, target

    wrong_capability_contract = _target_contract(
        capability="desktop.app_control",
        step_id="open-app",
        target={
            "kind": "desktop_ui",
            "action": "shortcut",
            "app_name": "Word",
        },
    )
    wrong_capability = coordinator.record_tool_outcome(
        wrong_capability_contract,
        coordinator.initial(wrong_capability_contract),
        _verified_target_outcome("desktop.app_control"),
        run_id=wrong_capability_contract.run_id,
        source_tool_call_id="wrong-capability",
        source_step_id="open-app",
        observed={
            "state": "fulfilled",
            "target": {
                "kind": "desktop_app",
                "action": "keyboard_shortcut",
                "app_name": "Word",
            },
        },
    )
    assert wrong_capability.completed is False


def test_effectful_criterion_rejects_a_verifier_bound_to_the_wrong_source() -> None:
    contract = GoalContract(
        contract_id="goal-play-1",
        run_id="run-1",
        original_goal="Play the requested track",
        criteria=(
            GoalCriterion(
                criterion_id="playback",
                description="The requested track is actively playing",
                effectful=True,
                required_capabilities=("media.playback",),
                required_effects=("media.playback_requested",),
                expected={"state": "playing", "entity": "track-1"},
            ),
        ),
    )
    coordinator = GoalCoordinator()
    assessment = coordinator.initial(contract)
    assessment = coordinator.record_tool_outcome(
        contract,
        assessment,
        _successful_playback_outcome(),
        run_id="run-1",
        source_tool_call_id="play-call-1",
    )

    assessment = coordinator.record_verifier_evidence(
        contract,
        assessment,
        criterion_id="playback",
        run_id="run-1",
        source_tool_call_id="another-play-call",
        verifier_tool_call_id="status-call-1",
        observed={"state": "playing", "entity": "track-1"},
    )

    assert assessment.completed is False
    assert assessment.satisfied_criterion_ids == ()
    assert assessment.unsatisfied_criterion_ids == ("playback",)


def test_alias_evidence_does_not_complete_the_playback_criterion() -> None:
    contract = GoalContract(
        contract_id="goal-play-2",
        run_id="run-2",
        original_goal="Play the requested track",
        criteria=(
            GoalCriterion(
                criterion_id="identity",
                description="Resolve a trusted playable alias",
                expected={"alias": "Moonlight"},
            ),
            GoalCriterion(
                criterion_id="playback",
                description="The requested track is actively playing",
                effectful=True,
                required_capabilities=("media.playback",),
                required_effects=("media.playback_requested",),
                expected={"state": "playing", "entity": "Moonlight"},
            ),
        ),
    )
    coordinator = GoalCoordinator()
    assessment = coordinator.initial(contract)
    assessment = coordinator.record_verifier_evidence(
        contract,
        assessment,
        criterion_id="identity",
        run_id="run-2",
        source_tool_call_id="alias-extract-1",
        verifier_tool_call_id="alias-extract-1",
        observed={"alias": "Moonlight", "source": "trusted-identity-page"},
    )

    assert assessment.completed is False
    assert assessment.satisfied_criterion_ids == ("identity",)
    assert assessment.unsatisfied_criterion_ids == ("playback",)


def test_correlated_playback_verifier_completes_the_original_goal() -> None:
    contract = GoalContract(
        contract_id="goal-play-3",
        run_id="run-3",
        original_goal="Play the requested track",
        criteria=(
            GoalCriterion(
                criterion_id="playback",
                description="The requested track is actively playing",
                effectful=True,
                required_capabilities=("media.playback",),
                required_effects=("media.playback_requested",),
                expected={"state": "playing", "entity": "Moonlight"},
            ),
        ),
    )
    coordinator = GoalCoordinator()
    assessment = coordinator.record_tool_outcome(
        contract,
        coordinator.initial(contract),
        _successful_playback_outcome(),
        run_id="run-3",
        source_tool_call_id="play-call-3",
    )
    assessment = coordinator.record_verifier_evidence(
        contract,
        assessment,
        criterion_id="playback",
        run_id="run-3",
        source_tool_call_id="play-call-3",
        verifier_tool_call_id="status-call-3",
        observed={"state": "playing", "entity": "Moonlight", "volume": 0.5},
    )

    assert assessment.completed is True
    assert assessment.satisfied_criterion_ids == ("playback",)
    assert assessment.unsatisfied_criterion_ids == ()


def test_declared_verifier_step_is_mandatory_and_round_trips_with_lineage() -> None:
    contract = GoalContract(
        contract_id="goal-typed-verified",
        run_id="run-typed-verified",
        original_goal="Write the generated report into the requested app",
        criteria=(
            GoalCriterion(
                criterion_id="typed-report",
                description="The exact report is present in the target app",
                effectful=True,
                required_capabilities=("desktop.ui_operation",),
                expected={"state": "fulfilled"},
                source_step_ids=("insert-report",),
                verifier_step_ids=("verify-report",),
            ),
        ),
    )
    verified_source = ToolOutcome(
        tool_name="desktop.type_into_ui_element",
        capabilities=("desktop.ui_operation",),
        status=OutcomeStatus.SUCCESS,
        reason="typed",
        retryable=False,
        effects=(),
        verification=VerificationStatus.VERIFIED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({"provider": "test"}),
        raw={"ok": True, "postcondition_verified": True},
    )
    coordinator = GoalCoordinator()
    source_only = coordinator.record_tool_outcome(
        contract,
        coordinator.initial(contract),
        verified_source,
        run_id=contract.run_id,
        source_tool_call_id="call-insert",
        source_step_id="insert-report",
        plan_id="plan-report",
        observed={"state": "fulfilled"},
    )

    wrong_verifier = coordinator.record_verifier_evidence(
        contract,
        source_only,
        criterion_id="typed-report",
        run_id=contract.run_id,
        source_tool_call_id="call-insert",
        verifier_tool_call_id="call-wrong-verifier",
        source_step_id="insert-report",
        verifier_step_id="inspect-report",
        plan_id="plan-report",
        observed={"state": "fulfilled"},
    )
    completed = coordinator.record_verifier_evidence(
        contract,
        wrong_verifier,
        criterion_id="typed-report",
        run_id=contract.run_id,
        source_tool_call_id="call-insert",
        verifier_tool_call_id="call-verifier",
        source_step_id="insert-report",
        verifier_step_id="verify-report",
        plan_id="plan-report",
        observed={"state": "fulfilled"},
    )

    assert source_only.completed is False
    assert wrong_verifier.completed is False
    assert completed.completed is True
    verifier = completed.evidence[-1]
    assert verifier.source_step_id == "insert-report"
    assert verifier.verifier_step_id == "verify-report"
    assert verifier.plan_id == "plan-report"
    assert coordinator.restore_assessment(contract, completed.to_payload()) == completed


def test_subgoal_budget_is_bound_to_one_unsatisfied_criterion() -> None:
    contract = GoalContract(
        contract_id="goal-play-4",
        run_id="run-4",
        original_goal="Play the requested track",
        max_subgoal_attempts=2,
        criteria=(
            GoalCriterion(
                criterion_id="playback",
                description="The requested track is actively playing",
                effectful=True,
                required_capabilities=("media.playback",),
            ),
        ),
    )
    coordinator = GoalCoordinator()
    assessment = coordinator.initial(contract)

    assessment, first = coordinator.open_subgoal(
        contract,
        assessment,
        criterion_id="playback",
        action="resolve_entity_alias",
        description="Resolve a trusted alias and return to playback",
        source_tool_call_id="play-call-4",
    )
    assessment, second = coordinator.open_subgoal(
        contract,
        assessment,
        criterion_id="playback",
        action="resolve_entity_alias",
        description="Resolve a trusted alias and return to playback",
        source_tool_call_id="play-call-4",
    )
    unchanged, exhausted = coordinator.open_subgoal(
        contract,
        assessment,
        criterion_id="playback",
        action="resolve_entity_alias",
        description="Resolve a trusted alias and return to playback",
        source_tool_call_id="play-call-4",
    )

    assert isinstance(first, BoundedSubgoal)
    assert isinstance(second, BoundedSubgoal)
    assert first.contract_id == contract.contract_id
    assert first.criterion_id == "playback"
    assert (first.attempt, second.attempt) == (1, 2)
    assert exhausted is None
    assert unchanged == assessment


def test_response_only_goal_can_complete_without_tools_and_round_trip() -> None:
    contract = GoalContract(
        contract_id="goal-answer-1",
        run_id="run-answer-1",
        original_goal="Explain why the sky looks blue",
        intent_kind="general",
        criteria=(
            GoalCriterion(
                criterion_id="response",
                description="Give the requested explanation",
                response_satisfiable=True,
            ),
        ),
    )
    coordinator = GoalCoordinator()
    assessment = coordinator.record_final_response(
        contract,
        coordinator.initial(contract),
        run_id="run-answer-1",
        response_text="Rayleigh scattering affects short wavelengths more strongly.",
    )

    assert assessment.completed is True
    assert GoalContract.from_payload(contract.to_payload()) == contract
    assert coordinator.restore_assessment(
        contract,
        assessment.to_payload(),
    ) == assessment


def test_goal_criterion_verification_predicates_round_trip_without_weakening() -> None:
    contract = GoalContract(
        contract_id="goal-semantic-artifact",
        run_id="run-semantic-artifact",
        original_goal="Analyze the data and write a useful report",
        criteria=(
            GoalCriterion(
                criterion_id="report",
                description="A durable and adequate report is present",
                effectful=True,
                required_capabilities=("data.analysis",),
                required_verification_predicates=(
                    "exact_file_content_present",
                    "semantic_artifact_adequacy",
                ),
                source_step_ids=("write-report",),
                verifier_step_ids=("read-report",),
            ),
        ),
    )

    restored = GoalContract.from_payload(contract.to_payload())

    assert restored == contract
    assert restored.criteria[0].required_verification_predicates == (
        "exact_file_content_present",
        "semantic_artifact_adequacy",
    )


def test_required_verification_predicates_must_share_exact_artifact_lineage() -> None:
    contract = GoalContract(
        contract_id="goal-semantic-artifact-ledger",
        run_id="run-semantic-artifact-ledger",
        original_goal="Analyze the data and write a useful report",
        criteria=(
            GoalCriterion(
                criterion_id="report",
                description="A durable and adequate report is present",
                effectful=True,
                required_capabilities=("data.analysis",),
                expected={"state": "fulfilled"},
                required_verification_predicates=(
                    "exact_file_content_present",
                    "semantic_artifact_adequacy",
                ),
                source_step_ids=("write-report",),
                verifier_step_ids=("read-report",),
            ),
        ),
    )
    source_outcome = ToolOutcome(
        tool_name="python.run",
        capabilities=("data.analysis",),
        status=OutcomeStatus.SUCCESS,
        reason="completed",
        retryable=False,
        effects=(),
        verification=VerificationStatus.UNVERIFIED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({"provider": "test"}),
        raw={"ok": True, "returncode": 0},
    )
    artifact_content = "private artifact body 🌙"
    artifact_bytes = artifact_content.encode("utf-8")
    lineage = {
        "state": "fulfilled",
        "observed_path": "reports/analysis.md",
        "content_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "content_length": len(artifact_bytes),
        "content": artifact_content,
    }
    coordinator = GoalCoordinator()
    source = coordinator.record_tool_outcome(
        contract,
        coordinator.initial(contract),
        source_outcome,
        run_id=contract.run_id,
        source_tool_call_id="call-write-report",
        source_step_id="write-report",
        plan_id="plan-report",
        observed={"state": "fulfilled", "content": "ordinary source summary"},
    )
    exact_readback = coordinator.record_verifier_evidence(
        contract,
        source,
        criterion_id="report",
        run_id=contract.run_id,
        source_tool_call_id="call-write-report",
        verifier_tool_call_id="call-read-report",
        source_step_id="write-report",
        verifier_step_id="read-report",
        plan_id="plan-report",
        verification_predicate="exact_file_content_present",
        observed=lineage,
    )
    completed = coordinator.record_verifier_evidence(
        contract,
        exact_readback,
        criterion_id="report",
        run_id=contract.run_id,
        source_tool_call_id="call-write-report",
        verifier_tool_call_id="call-read-report",
        source_step_id="write-report",
        verifier_step_id="read-report",
        plan_id="plan-report",
        verification_predicate="semantic_artifact_adequacy",
        observed=lineage,
    )

    assert exact_readback.completed is False
    assert completed.completed is True
    assert {item.verification_predicate for item in completed.evidence} >= {
        "exact_file_content_present",
        "semantic_artifact_adequacy",
    }
    assert exact_readback.evidence[-1].observed["content"] == artifact_content
    internal = completed.to_payload()
    internal_exact = next(
        item
        for item in internal["evidence"]
        if item["verification_predicate"] == "exact_file_content_present"
    )
    assert internal_exact["observed"]["content"] == artifact_content
    persisted = completed.to_persisted_payload()
    source_payload = next(
        item for item in persisted["evidence"] if not item["verification_predicate"]
    )
    exact_payload = next(
        item
        for item in persisted["evidence"]
        if item["verification_predicate"] == "exact_file_content_present"
    )
    assert source_payload["observed"]["content"] == "ordinary source summary"
    assert "content" not in exact_payload["observed"]
    assert exact_payload["observed"]["content_redacted"] is True
    assert exact_payload["observed"]["observed_path"] == "reports/analysis.md"
    assert exact_payload["observed"]["content_sha256"] == lineage["content_sha256"]
    assert exact_payload["observed"]["content_length"] == lineage["content_length"]
    forged_payload = completed.to_payload()
    semantic_payload = next(
        item
        for item in forged_payload["evidence"]
        if item["verification_predicate"] == "semantic_artifact_adequacy"
    )
    semantic_payload["observed"]["content_sha256"] = "b" * 64
    forged_restore = coordinator.restore_assessment(contract, forged_payload)
    assert forged_restore.completed is False
