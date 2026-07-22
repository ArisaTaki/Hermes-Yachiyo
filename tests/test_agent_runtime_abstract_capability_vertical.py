"""Cross-layer acceptance for model-proposed, Runtime-owned task subgoals."""

from __future__ import annotations

import json
from types import MappingProxyType

from apps.shell.agent.runtime.goal_contract import GoalContract, GoalCoordinator
from apps.shell.agent.runtime.model_intent_planning import (
    MODEL_INTENT_PLANNING_TOOL_NAME,
    direct_tool_selection_from_model_intent_proposal,
    goal_contract_payload_from_model_selection,
    model_intent_proposal_from_tool_requests,
)
from apps.shell.agent.runtime.tool_outcomes import (
    OutcomeStatus,
    ToolOutcome,
    VerificationStatus,
)


def _planning_call(arguments: dict[str, object]) -> dict[str, object]:
    return {
        "id": "provider-call-id-is-not-runtime-authority",
        "type": "function",
        "function": {
            "name": MODEL_INTENT_PLANNING_TOOL_NAME,
            "arguments": json.dumps(arguments),
        },
    }


def _verified_search_outcome() -> ToolOutcome:
    return ToolOutcome(
        tool_name="browser.search",
        capabilities=("browser.research",),
        status=OutcomeStatus.SUCCESS,
        reason="search_results_observed",
        retryable=False,
        effects=(),
        verification=VerificationStatus.VERIFIED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({"provider": "test-browser"}),
        raw={"ok": True, "postcondition_verified": True},
    )


def test_model_subgoals_require_exact_runtime_evidence_before_completion() -> None:
    goal = "Search the web for Python news, then search the web for Rust news"
    proposal = model_intent_proposal_from_tool_requests(
        [
            _planning_call(
                {
                    "intent_kind": "web_research",
                    "planning_goal": goal,
                    "action_evidence": "Search",
                    "subgoals": [
                        {
                            "capability_id": "browser.research",
                            "action_id": "search",
                            "planning_goal": "Search the web for Python news",
                            "action_evidence": "Search",
                            "input_slots": [
                                {
                                    "slot": "query",
                                    "value": "Python news",
                                    "evidence_quote": "Python news",
                                }
                            ],
                        },
                        {
                            "capability_id": "browser.research",
                            "action_id": "search",
                            "planning_goal": "search the web for Rust news",
                            "action_evidence": "search",
                            "input_slots": [
                                {
                                    "slot": "query",
                                    "value": "Rust news",
                                    "evidence_quote": "Rust news",
                                }
                            ],
                        },
                    ],
                }
            )
        ]
    )
    assert proposal is not None

    selection = direct_tool_selection_from_model_intent_proposal(
        proposal,
        goal,
        ["browser.search"],
    )
    assert [request["tool"] for request in selection.requests] == [
        "browser.search",
        "browser.search",
    ]
    contract = GoalContract.from_payload(
        goal_contract_payload_from_model_selection(selection, goal)
    ).bind_run("run-abstract-vertical")
    first, second = contract.criteria
    assert first.criterion_id != second.criterion_id
    assert first.source_step_ids != second.source_step_ids

    coordinator = GoalCoordinator()
    after_first = coordinator.record_tool_outcome(
        contract,
        coordinator.initial(contract),
        _verified_search_outcome(),
        run_id=contract.run_id,
        source_tool_call_id="call-python",
        source_step_id=first.source_step_ids[0],
        observed=first.expected,
    )
    wrong_second_target = coordinator.record_tool_outcome(
        contract,
        after_first,
        _verified_search_outcome(),
        run_id=contract.run_id,
        source_tool_call_id="call-rust-wrong-target",
        source_step_id=second.source_step_ids[0],
        observed=first.expected,
    )
    completed = coordinator.record_tool_outcome(
        contract,
        wrong_second_target,
        _verified_search_outcome(),
        run_id=contract.run_id,
        source_tool_call_id="call-rust",
        source_step_id=second.source_step_ids[0],
        observed=second.expected,
    )

    assert after_first.completed is False
    assert after_first.satisfied_criterion_ids == (first.criterion_id,)
    assert wrong_second_target.completed is False
    assert wrong_second_target.satisfied_criterion_ids == (first.criterion_id,)
    assert completed.completed is True
    assert completed.satisfied_criterion_ids == (
        first.criterion_id,
        second.criterion_id,
    )
