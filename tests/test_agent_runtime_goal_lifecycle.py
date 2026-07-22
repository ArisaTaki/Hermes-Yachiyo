from __future__ import annotations

import pytest

from apps.shell.agent.runtime.goal_contract import GoalContract, GoalCriterion
from apps.shell.agent.runtime.goal_runtime import (
    goal_contract_event_payload,
    planned_goal_contract_payload,
    runtime_goal_contract,
)
from apps.shell.agent.runtime.outcome_evaluator import evaluate_goal_contract_outcome


def _contract(
    *,
    run_id: str,
    description: str = "Provide the requested response",
) -> GoalContract:
    return GoalContract(
        contract_id="contract-stable",
        run_id=run_id,
        original_goal="Explain the immutable request",
        criteria=(
            GoalCriterion(
                criterion_id="criterion-response",
                description=description,
                response_satisfiable=True,
            ),
        ),
    )


def test_fallback_contract_uses_only_explicit_immutable_original_goal() -> None:
    contract = runtime_goal_contract(
        run_id="run-fallback",
        original_goal="Explain the immutable request",
        runtime_execution_envelope=None,
        runtime_execution_metadata=None,
        messages=[{"role": "user", "content": "a later mutable user message"}],
        timeline=[],
    )

    assert contract is not None
    assert contract.original_goal == "Explain the immutable request"


def test_planning_context_cannot_weaken_effectful_run_authority() -> None:
    original_goal = "删除文件\n\n目标：旧缓存"

    template = planned_goal_contract_payload(
        original_goal,
        allowed_tools=("workspace.delete",),
        planning_goal="你好",
    )
    contract = runtime_goal_contract(
        run_id="run-nested-goal",
        original_goal=original_goal,
        goal_contract_template=template,
        runtime_execution_envelope=None,
        runtime_execution_metadata=None,
        messages=[],
        timeline=[],
    )

    assert template["original_goal"] == original_goal
    assert template["intent_kind"] == "file_organization"
    assert any(criterion["effectful"] for criterion in template["criteria"])
    assert all(
        criterion["response_satisfiable"] is False
        for criterion in template["criteria"]
    )
    assert contract is not None
    assert contract.original_goal == original_goal


def test_effectful_goal_contract_compile_error_fails_closed(monkeypatch) -> None:
    def fail_decision(*_args, **_kwargs):
        raise ValueError("planner unavailable")

    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.runtime_planner.RuntimePlanner.decision",
        fail_decision,
    )

    with pytest.raises(ValueError, match="goal_contract_compile_failed"):
        planned_goal_contract_payload(
            "删除文件",
            allowed_tools=("workspace.delete",),
        )


@pytest.mark.parametrize(
    "user_goal",
    (
        "分析这份数据并输出报告，不要打开表格软件",
        "What is a summary? Please write a summary.",
        "Research https://example.com and save a report.",
        "Draft a message to Alex, but do not send it.",
        "Return exactly decision: ship in Slack.",
        "Return exactly decision: ship and open Slack.",
    ),
)
def test_compound_effectful_goal_never_falls_back_to_response_only_contract(
    monkeypatch,
    user_goal: str,
) -> None:
    def fail_decision(*_args, **_kwargs):
        raise ValueError("planner unavailable")

    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.runtime_planner.RuntimePlanner.decision",
        fail_decision,
    )

    with pytest.raises(ValueError, match="goal_contract_compile_failed"):
        planned_goal_contract_payload(
            user_goal,
            allowed_tools=("artifact.write", "desktop.safe_type_text"),
        )


def test_effectful_goal_cannot_fall_back_to_implicit_response_contract() -> None:
    with pytest.raises(ValueError, match="goal_contract_missing"):
        runtime_goal_contract(
            run_id="run-effectful-missing-contract",
            original_goal="删除文件",
            runtime_execution_envelope=None,
            runtime_execution_metadata=None,
            messages=[],
            timeline=[],
        )


def test_explicit_pure_chat_can_fall_back_when_contract_compile_fails(monkeypatch) -> None:
    def fail_decision(*_args, **_kwargs):
        raise ValueError("planner unavailable")

    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.runtime_planner.RuntimePlanner.decision",
        fail_decision,
    )

    template = planned_goal_contract_payload("你好", allowed_tools=())
    assert template["original_goal"] == "你好"
    assert template["criteria"][0]["response_satisfiable"] is True
    contract = runtime_goal_contract(
        run_id="run-pure-chat",
        original_goal="你好",
        goal_contract_template=template,
        runtime_execution_envelope=None,
        runtime_execution_metadata=None,
        messages=[],
        timeline=[],
    )

    assert contract is not None
    assert contract.original_goal == "你好"
    assert len(contract.criteria) == 1
    assert contract.criteria[0].response_satisfiable is True
    assert contract.criteria[0].effectful is False


@pytest.mark.parametrize(
    "goal",
    (
        "Summarize the confirmed preference",
        "审查上游实现或方案，列出风险、缺失测试和可验收结论。",
        "把整条流程的目标、关键决策、产物和风险整理成最终汇报。",
    ),
)
def test_contextual_advisory_goal_can_use_response_only_contract(goal: str) -> None:
    template = planned_goal_contract_payload(goal, allowed_tools=())

    assert template["original_goal"] == goal
    assert template["criteria"][0]["response_satisfiable"] is True
    assert template["criteria"][0]["effectful"] is False


@pytest.mark.parametrize(
    "goal",
    (
        "Summarize report.pdf",
        "Summarize the current web page",
        "Summarize the result and send it to Alex",
        "总结当前文档并保存",
        "Summarize the customer complaint",
        "Review the proposal and list risks",
        "Compare the two options",
    ),
)
def test_contextual_advisory_goal_with_external_effect_fails_closed(
    monkeypatch,
    goal: str,
) -> None:
    def fail_decision(*_args, **_kwargs):
        raise ValueError("planner unavailable")

    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.runtime_planner.RuntimePlanner.decision",
        fail_decision,
    )

    with pytest.raises(ValueError, match="goal_contract_compile_failed"):
        planned_goal_contract_payload(goal, allowed_tools=())


def test_ambiguous_advisory_response_contract_is_rejected_on_restore() -> None:
    goal = "Summarize the customer complaint"
    template = GoalContract(
        contract_id="contract-ambiguous-advisory",
        original_goal=goal,
        criteria=(
            GoalCriterion(
                criterion_id="criterion-ambiguous-advisory",
                description="Provide the requested summary",
                response_satisfiable=True,
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="goal_contract_invalid: response_only_nonconversation",
    ):
        runtime_goal_contract(
            run_id="run-ambiguous-advisory",
            original_goal=goal,
            goal_contract_template=template,
            runtime_execution_envelope=None,
            runtime_execution_metadata=None,
            messages=(),
            timeline=(),
        )


def test_unquoted_multiword_exact_response_contract_compiles() -> None:
    goal = "Return exactly decision: ship."

    template = planned_goal_contract_payload(
        goal,
        allowed_tools=("app.open", "communication.send"),
    )

    assert template["original_goal"] == goal
    assert template["criteria"][0]["response_satisfiable"] is True
    assert template["criteria"][0]["effectful"] is False


def test_messages_alone_cannot_create_a_fallback_contract() -> None:
    contract = runtime_goal_contract(
        run_id="run-message-only",
        runtime_execution_envelope=None,
        runtime_execution_metadata=None,
        messages=[{"role": "user", "content": "mutable message is not a root goal"}],
        timeline=[],
    )

    assert contract is None


def test_damaged_persisted_contract_fails_closed_instead_of_falling_back() -> None:
    with pytest.raises(ValueError, match="goal_contract_invalid"):
        runtime_goal_contract(
            run_id="run-damaged",
            original_goal="Fallback must not replace persisted state",
            runtime_execution_envelope=None,
            runtime_execution_metadata=None,
            messages=[],
            timeline=[
                {
                    "event": "agent.goal.contract",
                    "run_id": "run-damaged",
                    "goal_contract_json": "{damaged",
                }
            ],
        )


def test_damaged_explicit_contract_fails_closed_instead_of_falling_back() -> None:
    with pytest.raises(ValueError, match="goal_contract_invalid"):
        runtime_goal_contract(
            run_id="run-explicit-damaged",
            original_goal="Fallback must not replace an explicit template",
            runtime_execution_envelope={
                "task_core": {"goal_contract": "not-a-contract"}
            },
            runtime_execution_metadata=None,
            messages=[],
            timeline=[],
        )


def test_partial_direct_contract_template_fails_closed() -> None:
    with pytest.raises(ValueError, match="goal_contract_invalid"):
        runtime_goal_contract(
            run_id="run-partial-template",
            original_goal="Fallback must not replace a partial template",
            goal_contract_template={
                "contract_id": "partial-contract",
                "original_goal": "Fallback must not replace a partial template",
            },
            runtime_execution_envelope=None,
            runtime_execution_metadata=None,
            messages=[],
            timeline=[],
        )


def test_contract_with_partially_damaged_criteria_fails_closed() -> None:
    valid = _contract(run_id="").to_payload()
    valid["criteria"].append("damaged-criterion")

    with pytest.raises(ValueError, match="goal_contract_invalid"):
        runtime_goal_contract(
            run_id="run-damaged-criteria",
            original_goal="Explain the immutable request",
            goal_contract_template=valid,
            runtime_execution_envelope=None,
            runtime_execution_metadata=None,
            messages=[],
            timeline=[],
        )


def test_explicit_original_goal_must_match_the_restored_contract() -> None:
    contract = _contract(run_id="run-original-conflict")

    with pytest.raises(ValueError, match="goal_contract_conflict: original_goal"):
        runtime_goal_contract(
            run_id=contract.run_id,
            original_goal="A different root objective",
            goal_contract_template=contract,
            runtime_execution_envelope=None,
            runtime_execution_metadata=None,
            messages=[],
            timeline=[],
        )


def test_explicit_contract_bound_to_another_run_fails_closed() -> None:
    foreign = _contract(run_id="run-foreign")

    with pytest.raises(ValueError, match="goal_contract_invalid"):
        runtime_goal_contract(
            run_id="run-current",
            original_goal=foreign.original_goal,
            goal_contract_template=foreign,
            runtime_execution_envelope=None,
            runtime_execution_metadata=None,
            messages=[],
            timeline=[],
        )


def test_persisted_contract_event_from_another_run_fails_closed() -> None:
    foreign = _contract(run_id="run-foreign-event")

    with pytest.raises(ValueError, match="goal_contract_invalid"):
        runtime_goal_contract(
            run_id="run-current-event",
            original_goal=foreign.original_goal,
            runtime_execution_envelope=None,
            runtime_execution_metadata=None,
            messages=[],
            timeline=[
                {
                    "event": "agent.goal.contract",
                    "run_id": foreign.run_id,
                    **goal_contract_event_payload(foreign),
                }
            ],
        )


def test_second_persisted_contract_cannot_replace_canonical_criteria() -> None:
    first = _contract(run_id="run-conflict")
    conflicting = _contract(
        run_id="run-conflict",
        description="A later event tries to weaken or replace the criterion",
    )

    with pytest.raises(ValueError, match="goal_contract_conflict"):
        runtime_goal_contract(
            run_id="run-conflict",
            original_goal=first.original_goal,
            runtime_execution_envelope=None,
            runtime_execution_metadata=None,
            messages=[],
            timeline=[
                {
                    "event": "agent.goal.contract",
                    "run_id": "run-conflict",
                    **goal_contract_event_payload(first),
                },
                {
                    "event": "agent.goal.contract",
                    "run_id": "run-conflict",
                    **goal_contract_event_payload(conflicting),
                },
            ],
        )


def test_explicit_envelope_and_metadata_contracts_must_be_canonical_matches() -> None:
    envelope_contract = _contract(run_id="")
    metadata_contract = _contract(
        run_id="",
        description="Conflicting metadata criterion",
    )

    with pytest.raises(ValueError, match="goal_contract_conflict"):
        runtime_goal_contract(
            run_id="run-explicit-conflict",
            original_goal=envelope_contract.original_goal,
            runtime_execution_envelope={
                "task_core": {"goal_contract": envelope_contract.to_payload()}
            },
            runtime_execution_metadata={
                "goal_contract": metadata_contract.to_payload()
            },
            messages=[],
            timeline=[],
        )


def test_outcome_evaluator_rejects_a_second_different_contract() -> None:
    first = _contract(run_id="run-evaluator-conflict")
    conflicting = _contract(
        run_id="run-evaluator-conflict",
        description="A conflicting latest contract must not win",
    )
    events = [
        {
            "event_type": "agent.goal.contract",
            "run_id": first.run_id,
            "payload": goal_contract_event_payload(first),
        },
        {
            "event_type": "agent.goal.contract",
            "run_id": conflicting.run_id,
            "payload": goal_contract_event_payload(conflicting),
        },
    ]

    outcome = evaluate_goal_contract_outcome(
        {"run_id": first.run_id},
        events,
    )

    assert outcome is not None
    assert outcome.reason == "goal_contract_invalid"
