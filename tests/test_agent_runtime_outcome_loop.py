"""Behavioral tests for the canonical tool-outcome feedback loop."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest

from apps.shell.agent.runtime.custom_api_agent import RuntimeCustomApiAgentLoop
from apps.shell.agent.runtime.errors import AgentDirectOutcomeUnverified
from apps.shell.agent.runtime.goal_contract import GoalContract, GoalCriterion
from apps.shell.agent.runtime.outcome_loop import (
    OutcomeLoopCoordinator,
    OutcomeLoopDisposition,
    OutcomeLoopResult,
)
from apps.shell.agent.runtime.recovery import RecoveryPlan
from apps.shell.agent.runtime.recovery_actions import (
    RecoveryActionDisposition,
    RecoveryActionRegistry,
    RecoveryActionResult,
)
from apps.shell.agent.runtime.recovery_policies import RecoveryAssessment
from apps.shell.agent.runtime.tool_outcomes import (
    OutcomeStatus,
    ToolOutcome,
    UserAction,
    VerificationStatus,
)


def test_action_required_always_waits_for_user_and_preserves_authoritative_source() -> None:
    provenance = MappingProxyType({"trace_id": "trace-1"})
    outcome = ToolOutcome(
        tool_name="capability.operation",
        capabilities=("capability.execute",),
        status=OutcomeStatus.ACTION_REQUIRED,
        reason="permission_required",
        retryable=False,
        effects=(),
        verification=VerificationStatus.UNVERIFIED,
        user_action=UserAction(required=True, kind="permission"),
        recovery_hints=(),
        provenance=provenance,
        raw={"status": "permission_required"},
    )
    assessment = RecoveryAssessment(
        outcome=outcome,
        plan=None,
        tool_call_id=" source-call-1 ",
    )

    result = OutcomeLoopCoordinator().decide(
        assessment,
        recovery_action_result=RecoveryActionResult.complete("must not complete"),
    )

    assert result.disposition is OutcomeLoopDisposition.AWAIT_USER
    assert result.outcome is outcome
    assert result.recovery_plan is None
    assert result.source_tool_call_id == " source-call-1 "
    assert result.outcome.provenance is provenance
    assert result.terminal_output == ""
    assert result.recovery_action_result is not None
    assert (
        result.recovery_action_result.disposition
        is RecoveryActionDisposition.AWAIT_USER
    )


def test_terminal_recovery_completion_is_the_only_recovery_output_that_completes() -> None:
    outcome = ToolOutcome(
        tool_name="capability.operation",
        capabilities=("capability.execute",),
        status=OutcomeStatus.PARTIAL,
        reason="entity_missing",
        retryable=True,
        effects=(),
        verification=VerificationStatus.UNVERIFIED,
        user_action=None,
        recovery_hints=("resolve_entity",),
        provenance=MappingProxyType({}),
        raw={"status": "partial"},
    )
    plan = RecoveryPlan(
        strategy_id="resolve-entity",
        action="resolve_entity",
        recovery_hint="resolve_entity",
        required_capabilities=("knowledge.resolve",),
        source_status=outcome.status,
        source_reason=outcome.reason,
        scope_id="attempt:1",
    )
    assessment = RecoveryAssessment(
        outcome=outcome,
        plan=plan,
        tool_call_id="source-call-2",
    )
    recovery = RecoveryActionResult.complete("recovered result")

    result = OutcomeLoopCoordinator().decide(
        assessment,
        recovery_action_result=recovery,
    )

    assert result.disposition is OutcomeLoopDisposition.COMPLETED
    assert result.terminal_output == "recovered result"
    assert result.outcome is outcome
    assert result.recovery_plan is plan
    assert result.source_tool_call_id == "source-call-2"
    assert result.recovery_action_result is recovery


def test_recovery_continuation_returns_continue_plan() -> None:
    outcome = ToolOutcome(
        tool_name="capability.operation",
        capabilities=("capability.execute",),
        status=OutcomeStatus.FAILED,
        reason="location_missing",
        retryable=True,
        effects=(),
        verification=VerificationStatus.NOT_REQUIRED,
        user_action=None,
        recovery_hints=("resolve_location",),
        provenance=MappingProxyType({}),
        raw={"status": "failed"},
    )
    plan = RecoveryPlan(
        strategy_id="resolve-location",
        action="resolve_location",
        recovery_hint="resolve_location",
        required_capabilities=("location.resolve",),
        source_status=outcome.status,
        source_reason=outcome.reason,
        scope_id="attempt:2",
    )
    assessment = RecoveryAssessment(outcome, plan, "source-call-3")
    recovery = RecoveryActionResult.continue_plan(reason="discovery_completed")

    result = OutcomeLoopCoordinator().decide(
        assessment,
        recovery_action_result=recovery,
    )

    assert result.disposition is OutcomeLoopDisposition.CONTINUE_PLAN
    assert result.terminal_output == ""
    assert result.reason == "discovery_completed"
    assert result.outcome is outcome
    assert result.recovery_plan is plan


@pytest.mark.parametrize("status", [OutcomeStatus.FAILED, OutcomeStatus.PARTIAL])
@pytest.mark.parametrize(
    "recovery",
    [
        RecoveryActionResult.not_handled(reason="adapter_unavailable"),
        RecoveryActionResult.failed(reason="recovery_execution_failed"),
    ],
    ids=("not-handled", "execution-failed"),
)
def test_unresolved_retryable_recovery_requests_model_replan(
    status: OutcomeStatus,
    recovery: RecoveryActionResult,
) -> None:
    outcome = ToolOutcome(
        tool_name="capability.operation",
        capabilities=("capability.execute",),
        status=status,
        reason="target_unresolved",
        retryable=True,
        effects=(),
        verification=VerificationStatus.UNVERIFIED,
        user_action=None,
        recovery_hints=("resolve_target",),
        provenance=MappingProxyType({}),
        raw={"status": status.value},
    )
    plan = RecoveryPlan(
        strategy_id="resolve-target",
        action="resolve_target",
        recovery_hint="resolve_target",
        required_capabilities=("target.resolve",),
        source_status=outcome.status,
        source_reason=outcome.reason,
        scope_id="attempt:3",
    )

    result = OutcomeLoopCoordinator().decide(
        RecoveryAssessment(outcome, plan, "source-call-4"),
        recovery_action_result=recovery,
    )

    assert result.disposition is OutcomeLoopDisposition.REPLAN_MODEL
    assert result.reason == recovery.reason
    assert result.outcome is outcome
    assert result.recovery_plan is plan
    assert result.source_tool_call_id == "source-call-4"


def test_nonretryable_failure_is_terminally_failed() -> None:
    outcome = ToolOutcome(
        tool_name="capability.operation",
        capabilities=("capability.execute",),
        status=OutcomeStatus.FAILED,
        reason="policy_denied",
        retryable=False,
        effects=(),
        verification=VerificationStatus.NOT_REQUIRED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({}),
        raw={"status": "failed"},
    )

    result = OutcomeLoopCoordinator().decide(
        RecoveryAssessment(outcome, None, "source-call-5"),
        recovery_action_result=RecoveryActionResult.not_handled(
            reason="no_recovery_plan"
        ),
    )

    assert result.disposition is OutcomeLoopDisposition.FAILED
    assert result.reason == "policy_denied"
    assert result.terminal_output == ""
    assert result.outcome is outcome
    assert result.recovery_plan is None


def test_user_goal_blocked_tool_returns_control_to_model_without_failing_task() -> None:
    outcome = ToolOutcome(
        tool_name="terminal.run",
        capabilities=("terminal.execute",),
        status=OutcomeStatus.FAILED,
        reason="blocked_by_user_goal",
        retryable=False,
        effects=(),
        verification=VerificationStatus.NOT_REQUIRED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({}),
        raw={
            "ok": False,
            "blocked_by_user_goal": True,
            "error": "user constraint",
        },
    )

    result = OutcomeLoopCoordinator().decide(
        RecoveryAssessment(outcome, None, "blocked-tool-call"),
        recovery_action_result=RecoveryActionResult.not_handled(
            reason="no_recovery_plan"
        ),
    )

    assert result.disposition is OutcomeLoopDisposition.REPLAN_MODEL
    assert result.reason == "continue_without_tool"
    assert result.terminal_output == ""


def test_structured_policy_refusal_returns_control_to_model_for_explanation() -> None:
    outcome = ToolOutcome(
        tool_name="workspace.write_patch",
        capabilities=("workspace.write",),
        status=OutcomeStatus.FAILED,
        reason="workspace_boundary_refusal",
        retryable=False,
        effects=(),
        verification=VerificationStatus.NOT_REQUIRED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({}),
        raw={
            "ok": False,
            "policy_refusal": True,
            "completion_impact": "report_refusal",
        },
    )

    result = OutcomeLoopCoordinator().decide(
        RecoveryAssessment(outcome, None, "workspace-refusal-call"),
        recovery_action_result=RecoveryActionResult.not_handled(
            reason="no_recovery_plan"
        ),
    )

    assert result.disposition is OutcomeLoopDisposition.REPLAN_MODEL
    assert result.reason == "report_refusal"
    assert result.terminal_output == ""


@pytest.mark.parametrize(
    ("remaining_plan", "expected"),
    [
        (False, OutcomeLoopDisposition.COMPLETED),
        (True, OutcomeLoopDisposition.CONTINUE_PLAN),
    ],
)
def test_success_completes_only_when_no_plan_remains(
    remaining_plan: bool,
    expected: OutcomeLoopDisposition,
) -> None:
    outcome = ToolOutcome(
        tool_name="capability.operation",
        capabilities=("capability.execute",),
        status=OutcomeStatus.SUCCESS,
        reason="completed",
        retryable=False,
        effects=("state_changed",),
        verification=VerificationStatus.VERIFIED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({}),
        raw={"status": "success"},
    )

    result = OutcomeLoopCoordinator().decide(
        RecoveryAssessment(outcome, None, "source-call-6"),
        remaining_plan=remaining_plan,
    )

    assert result.disposition is expected
    assert result.outcome is outcome
    assert result.source_tool_call_id == "source-call-6"
    assert result.terminal_output == ""


def test_partial_without_admissible_recovery_stays_partial() -> None:
    outcome = ToolOutcome(
        tool_name="capability.operation",
        capabilities=("capability.execute",),
        status=OutcomeStatus.PARTIAL,
        reason="result_incomplete",
        retryable=True,
        effects=("partial_effect",),
        verification=VerificationStatus.UNVERIFIED,
        user_action=None,
        recovery_hints=("optional_resolution",),
        provenance=MappingProxyType({}),
        raw={"status": "partial"},
    )

    result = OutcomeLoopCoordinator().decide(
        RecoveryAssessment(outcome, None, "source-call-7"),
        recovery_action_result=RecoveryActionResult.not_handled(
            reason="recovery_plan_unavailable"
        ),
    )

    assert result.disposition is OutcomeLoopDisposition.PARTIAL
    assert result.reason == "result_incomplete"
    assert result.outcome is outcome
    assert result.recovery_plan is None
    assert result.terminal_output == ""


def test_retryable_failure_without_automatic_plan_requests_model_replan() -> None:
    outcome = ToolOutcome(
        tool_name="capability.operation",
        capabilities=("capability.execute",),
        status=OutcomeStatus.FAILED,
        reason="temporary_failure",
        retryable=True,
        effects=(),
        verification=VerificationStatus.NOT_REQUIRED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({}),
        raw={"status": "failed"},
    )
    recovery = RecoveryActionResult.not_handled(reason="no_automatic_recovery")

    result = OutcomeLoopCoordinator().decide(
        RecoveryAssessment(outcome, None, "source-call-8"),
        recovery_action_result=recovery,
    )

    assert result.disposition is OutcomeLoopDisposition.REPLAN_MODEL
    assert result.reason == "no_automatic_recovery"
    assert result.outcome is outcome
    assert result.recovery_plan is None


def test_retryable_failure_without_a_recovery_attempt_still_requests_replan() -> None:
    outcome = ToolOutcome(
        tool_name="capability.operation",
        capabilities=("capability.execute",),
        status=OutcomeStatus.FAILED,
        reason="temporary_failure",
        retryable=True,
        effects=(),
        verification=VerificationStatus.NOT_REQUIRED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({}),
        raw={"status": "failed"},
    )

    result = OutcomeLoopCoordinator().decide(
        RecoveryAssessment(outcome, None, "source-call-without-attempt")
    )

    assert result.disposition is OutcomeLoopDisposition.REPLAN_MODEL
    assert result.reason == "temporary_failure"
    assert result.outcome is outcome


def test_terminal_output_requires_a_terminal_recovery_completion() -> None:
    outcome = ToolOutcome(
        tool_name="capability.operation",
        capabilities=("capability.execute",),
        status=OutcomeStatus.SUCCESS,
        reason="completed",
        retryable=False,
        effects=(),
        verification=VerificationStatus.NOT_REQUIRED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({}),
        raw={"status": "success"},
    )

    with pytest.raises(ValueError, match="terminal recovery completion"):
        OutcomeLoopResult(
            disposition=OutcomeLoopDisposition.COMPLETED,
            outcome=outcome,
            recovery_plan=None,
            source_tool_call_id="source-call-9",
            terminal_output="forged output",
        )


@pytest.mark.parametrize(
    ("retryable", "expected"),
    [
        (True, OutcomeLoopDisposition.REPLAN_MODEL),
        (False, OutcomeLoopDisposition.FAILED),
    ],
)
def test_skipped_outcome_always_has_a_terminal_or_replan_intent(
    retryable: bool,
    expected: OutcomeLoopDisposition,
) -> None:
    outcome = ToolOutcome(
        tool_name="capability.operation",
        capabilities=("capability.execute",),
        status=OutcomeStatus.SKIPPED,
        reason="operation_skipped",
        retryable=retryable,
        effects=(),
        verification=VerificationStatus.NOT_REQUIRED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({}),
        raw={"status": "skipped"},
    )

    result = OutcomeLoopCoordinator().decide(
        RecoveryAssessment(outcome, None, "source-call-10")
    )

    assert result.disposition is expected
    assert result.outcome is outcome
    assert result.reason == "operation_skipped"


class _LoopBudget:
    def claim_model_call(self) -> None:
        return None


class _LoopProjection:
    @staticmethod
    def assistant_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
        return {"role": "assistant", "content": message.get("content", "")}

    @staticmethod
    def artifact_completion(
        _timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
    ) -> None:
        return None

    @staticmethod
    def loop_limit_detail(_timeline: list[dict[str, Any]]) -> str:
        return "loop exhausted"


def _effectful_model_tool_contract(
    *,
    run_id: str,
    original_goal: str,
    bindings: tuple[tuple[str, str, dict[str, Any]], ...],
) -> GoalContract:
    return GoalContract(
        contract_id=f"goal-contract-{run_id}",
        run_id=run_id,
        original_goal=original_goal,
        criteria=tuple(
            GoalCriterion(
                criterion_id=f"goal-criterion-{index}-{run_id}",
                description=f"Execute the exact {tool_name} request",
                effectful=True,
                required_capabilities=(capability_id,),
                expected={"target": dict(target)},
                source_step_ids=(f"model-tool-{index}",),
            )
            for index, (tool_name, capability_id, target) in enumerate(
                bindings,
                start=1,
            )
        ),
    )


class _RecoveryAdapter:
    action = "resolve_target"

    def __init__(self, result: RecoveryActionResult) -> None:
        self._result = result

    @staticmethod
    def supports(_context: Any) -> bool:
        return True

    def execute(self, _context: Any) -> RecoveryActionResult:
        return self._result


@pytest.mark.parametrize(
    ("first_result", "expected_reason", "expected_model_calls"),
    [
        pytest.param(
            {
                "ok": False,
                "reason": "policy_denied",
                "error": "denied",
                "retryable": False,
            },
            "loop_exhausted",
            2,
            id="nonretryable-model-tool-failure-replans-once",
        ),
        pytest.param(
            {
                "ok": False,
                "reason": "temporary_failure",
                "error": "temporary",
                "retryable": True,
            },
            "loop_exhausted",
            2,
            id="retryable-failure-replans",
        ),
        pytest.param(
            {
                "ok": False,
                "reason": "blocked_by_user_goal",
                "error": "user constraint",
                "blocked_by_user_goal": True,
                "retryable": False,
            },
            "loop_exhausted",
            2,
            id="user-goal-block-continues-without-tool",
        ),
        pytest.param(
            {
                "ok": False,
                "permission_error": True,
                "permission_targets": ["automation"],
                "error": "permission required",
            },
            "permission_required",
            1,
            id="permission-waits-for-user",
        ),
    ],
)
def test_model_selected_batch_routes_early_failure_before_later_success(
    first_result: dict[str, Any],
    expected_reason: str,
    expected_model_calls: int,
) -> None:
    run_id = "run-model-selected-batch"
    goal_contract = _effectful_model_tool_contract(
        run_id=run_id,
        original_goal="Execute the exact terminal and workspace-read test batch",
        bindings=(
            (
                "terminal.run",
                "terminal.execution",
                {"kind": "local_compute", "command": "test command"},
            ),
            (
                "workspace.read",
                "file.workspace_read",
                {"kind": "workspace_file", "action": "read", "path": "README.md"},
            ),
        ),
    )
    model_calls = 0

    def call_model(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal model_calls
        model_calls += 1
        return {
            "role": "assistant",
            "content": "use batch" if model_calls == 1 else "continued safely",
        }

    def tool_requests_from_message(
        _message: dict[str, Any],
        content: str,
    ) -> list[dict[str, Any]]:
        if content != "use batch":
            return []
        return [
            {
                "protocol": "json_fallback",
                "tool": "terminal.run",
                "tool_call_id": "batch-failed-first",
                "input": {"command": "test command"},
            },
            {
                "protocol": "json_fallback",
                "tool": "workspace.read",
                "tool_call_id": "batch-success-later",
                "input": {"path": "README.md"},
            },
        ]

    def run_tool_requests(
        requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        for request in requests:
            result = (
                dict(first_result)
                if request["tool_call_id"] == "batch-failed-first"
                else {
                    "ok": True,
                    "postcondition_verified": True,
                    "data": {
                        "content": "read",
                        "target": {
                            "kind": "workspace_file",
                            "action": "read",
                            "path": "README.md",
                        },
                    },
                }
            )
            timeline.append(
                _trusted_bound_outcome_terminal(
                    request,
                    run_id=str(_kwargs.get("run_id") or ""),
                    result=result,
                )
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": ["terminal.run", "workspace.read"]
            }
        },
        run_budget=lambda _run_id, _timeline: _LoopBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=2,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=tool_requests_from_message,
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_LoopProjection(),
        run_tool_requests=run_tool_requests,
        error_type=RuntimeError,
    )

    if expected_reason == "permission_required":
        with pytest.raises(AgentDirectOutcomeUnverified) as exc_info:
            loop.run(
                {"name": "Agent"},
                "ordinary request",
                broker=object(),
                timeline=[],
                artifacts=[],
                messages=[{"role": "user", "content": "ordinary request"}],
                start_iteration=0,
                run_id=run_id,
                runtime_execution_metadata={
                    "goal_contract": goal_contract.to_payload(),
                },
            )
        assert exc_info.value.reason == expected_reason
    else:
        with pytest.raises(RuntimeError, match="loop exhausted"):
            loop.run(
                {"name": "Agent"},
                "ordinary request",
                broker=object(),
                timeline=[],
                artifacts=[],
                messages=[{"role": "user", "content": "ordinary request"}],
                start_iteration=0,
                run_id=run_id,
                runtime_execution_metadata={
                    "goal_contract": goal_contract.to_payload(),
                },
            )

    assert model_calls == expected_model_calls


@pytest.mark.parametrize(
    (
        "recovery_result",
        "expected_result",
        "expected_model_calls",
        "expected_lifecycle_event",
    ),
    [
        pytest.param(
            RecoveryActionResult.continue_plan(
                reason="recovery_observation_ready"
            ),
            "continued model result",
            [1, 2],
            "agent.recovery.completed",
            id="continue-plan",
        ),
        pytest.param(
            RecoveryActionResult.not_handled(reason="adapter_unavailable"),
            "continued model result",
            [1, 2],
            "agent.recovery.skipped",
            id="not-handled-replans",
        ),
        pytest.param(
            RecoveryActionResult.failed(reason="recovery_execution_failed"),
            "continued model result",
            [1, 2],
            "agent.recovery.failed",
            id="execution-failure-replans",
        ),
        pytest.param(
            RecoveryActionResult.complete("terminal recovered result"),
            "terminal recovered result",
            [1],
            "agent.recovery.completed",
            id="terminal-completion",
        ),
    ],
)
def test_model_selected_recovery_disposition_controls_the_next_loop_intent(
    monkeypatch: pytest.MonkeyPatch,
    recovery_result: RecoveryActionResult,
    expected_result: str,
    expected_model_calls: list[int],
    expected_lifecycle_event: str,
) -> None:
    outcome = ToolOutcome(
        tool_name="capability.operation",
        capabilities=("capability.execute",),
        status=OutcomeStatus.PARTIAL,
        reason="target_unresolved",
        retryable=True,
        effects=("partial_effect",),
        verification=VerificationStatus.UNVERIFIED,
        user_action=None,
        recovery_hints=("resolve_target",),
        provenance=MappingProxyType({}),
        raw={"status": "partial"},
    )
    plan = RecoveryPlan(
        strategy_id="resolve-target",
        action="resolve_target",
        recovery_hint="resolve_target",
        required_capabilities=("target.resolve",),
        source_status=outcome.status,
        source_reason=outcome.reason,
        scope_id="attempt:model-selected",
    )
    assessment = RecoveryAssessment(outcome, plan, "source-model-call")

    def decide_terminal_batch(
        coordinator: OutcomeLoopCoordinator,
        **kwargs: Any,
    ) -> tuple[OutcomeLoopResult, ...]:
        recovery_action = kwargs["recovery_action"]
        return (
            coordinator.decide(
                assessment,
                recovery_action_result=recovery_action(assessment),
                remaining_plan=True,
            ),
        )

    monkeypatch.setattr(
        OutcomeLoopCoordinator,
        "decide_terminal_batch",
        decide_terminal_batch,
    )
    responses = [
        {"role": "assistant", "content": "use tool"},
        {"role": "assistant", "content": "continued model result"},
    ]
    model_calls: list[int] = []

    def call_model(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        model_calls.append(len(model_calls) + 1)
        return responses.pop(0)

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["capability.operation"]}
        },
        run_budget=lambda _run_id, _timeline: _LoopBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, content: (
            [
                {
                    "protocol": "tool_calls",
                    "tool": "capability.operation",
                    "tool_call_id": "source-model-call",
                    "input": {},
                }
            ]
            if content == "use tool"
            else []
        ),
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_LoopProjection(),
        run_tool_requests=lambda *_args, **_kwargs: None,
        error_type=RuntimeError,
        recovery_action_registry=RecoveryActionRegistry(
            (_RecoveryAdapter(recovery_result),)
        ),
    )
    loop._direct_daily_desktop_sequence_result = (
        lambda *_args, **_kwargs: "legacy partial result"
    )

    timeline: list[dict[str, Any]] = []
    result = loop.run(
        {"name": "Agent"},
        "ordinary request",
        broker=object(),
        timeline=timeline,
        artifacts=[],
    )

    assert result == expected_result
    assert model_calls == expected_model_calls
    lifecycle = [
        event["event"]
        for event in timeline
        if str(event.get("event") or "").startswith("agent.recovery.")
    ]
    assert lifecycle == ["agent.recovery.planned", expected_lifecycle_event]


def test_direct_runtime_planner_early_failure_is_not_hidden_by_later_success() -> None:
    model_calls: list[list[dict[str, Any]]] = []

    def call_model(
        _base_url: str,
        _model: str,
        _api_key: str,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        model_calls.append([dict(message) for message in messages])
        return {"role": "assistant", "content": "replanned safely"}

    def run_tool_requests(
        tool_requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        results = {
            "direct-media-failed": {
                "ok": False,
                "error": "temporary provider failure",
                "retryable": True,
                "summary": "playback failed",
            },
            "direct-verify-succeeded": {
                "ok": True,
                "verified": True,
                "postcondition_verified": True,
                "target_reached": True,
                "summary": "verification passed",
            },
        }
        for request in tool_requests:
            tool_name = str(request.get("tool") or "")
            tool_call_id = str(request.get("tool_call_id") or "")
            timeline.append(
                _trusted_outcome_terminal(
                    run_id=str(_kwargs.get("run_id") or ""),
                    tool=tool_name,
                    tool_call_id=tool_call_id,
                    input_preview=dict(request.get("input") or {}),
                    result=results[tool_call_id],
                )
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": ["media.apple_music_play", "desktop.verify"]
            }
        },
        run_budget=lambda _run_id, _timeline: _LoopBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=2,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_LoopProjection(),
        run_tool_requests=run_tool_requests,
        error_type=RuntimeError,
    )
    timeline: list[dict[str, Any]] = []

    result = loop.run(
        {"name": "Agent"},
        "play something and verify it",
        broker=object(),
        timeline=timeline,
        artifacts=[],
        run_id="run-direct-early-failure",
        original_goal="",
        direct_tool_requests=[
            {
                "protocol": "json_fallback",
                "tool": "media.apple_music_play",
                "tool_call_id": "direct-media-failed",
                "input": {"query": "Example"},
                "source": "runtime_planner",
                "planning_reason": "explicit_full_plan",
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.verify",
                "tool_call_id": "direct-verify-succeeded",
                "input": {"app_name": "Music"},
                "source": "runtime_planner",
                "planning_reason": "explicit_full_plan",
            },
        ],
    )

    assert result == "replanned safely"
    assert len(model_calls) == 1
    assert not any(
        event.get("event") == "agent.desktop.intent_completed" for event in timeline
    )


def test_direct_runtime_planner_outcomes_keep_order_and_unfinished_plan_pending() -> None:
    run_id = "run-direct-outcome-order"
    timeline = [
        _trusted_outcome_terminal(
            run_id=run_id,
            tool="workspace.list",
            tool_call_id="direct-list",
            result={"ok": True, "entries": []},
        ),
        _trusted_outcome_terminal(
            run_id=run_id,
            tool="workspace.read",
            tool_call_id="direct-read",
            result={"ok": True, "content": "ready"},
        ),
    ]
    planned_tool_requests = [
        {"tool": "workspace.list", "tool_call_id": "direct-list"},
        {"tool": "workspace.read", "tool_call_id": "direct-read"},
        {"tool": "artifact.write", "tool_call_id": "direct-write"},
    ]

    results = OutcomeLoopCoordinator().decide_terminal_batch(
        timeline=timeline,
        start_index=0,
        run_id=run_id,
        allowed_tools=["workspace.list", "workspace.read", "artifact.write"],
        planned_tool_call_ids=[
            str(request.get("tool_call_id") or "")
            for request in planned_tool_requests
        ],
    )

    assert [result.source_tool_call_id for result in results] == [
        "direct-list",
        "direct-read",
    ]
    assert [result.disposition for result in results] == [
        OutcomeLoopDisposition.CONTINUE_PLAN,
        OutcomeLoopDisposition.CONTINUE_PLAN,
    ]


def _trusted_outcome_terminal(
    *,
    run_id: str,
    tool_call_id: str,
    result: dict[str, Any],
    tool: str = "media.apple_music_play",
    input_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "event": "agent.tool.call",
        "run_id": run_id,
        "actor": "native_runtime",
        "execution_authority": "runtime_tool_executor",
        "detail": tool,
        "tool": tool,
        "tool_call_id": tool_call_id,
        "result": result,
    }
    if input_preview is not None:
        event["input_preview"] = dict(input_preview)
    return event


def _trusted_bound_outcome_terminal(
    request: dict[str, Any],
    *,
    run_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    event = _trusted_outcome_terminal(
        run_id=run_id,
        tool=str(request["tool"]),
        tool_call_id=str(request["tool_call_id"]),
        input_preview=dict(request.get("input") or {}),
        result=result,
    )
    for key in (
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "step_id",
        "planner_step_id",
        "request_id",
        "goal_contract_id",
        "goal_criterion_id",
        "root_goal_unchanged",
        "capability_id",
        "action_target",
    ):
        if key in request:
            event[key] = request[key]
    return event


def _played_media_result(query: str = "Moonlight") -> dict[str, Any]:
    return {
        "ok": True,
        "postcondition_verified": True,
        "data": {
            "query": query,
            "status": "played",
            "track": query,
            "track_identity_verified": True,
            "player_state": "playing",
            "playback_started": True,
            "postcondition_verified": True,
        },
    }


def _missing_media_result(query: str = "Moonlight") -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "query": query,
            "status": "not_found",
            "outcome": "partial",
            "background_safe": True,
            "library_search_completed": True,
        },
    }


@pytest.mark.parametrize(
    ("first_result", "conflicting_result", "expected_status", "recovery_calls"),
    (
        (
            _played_media_result(),
            _missing_media_result(),
            OutcomeStatus.SUCCESS,
            0,
        ),
        (
            _missing_media_result(),
            _played_media_result(),
            OutcomeStatus.PARTIAL,
            1,
        ),
    ),
    ids=("success-before-partial", "partial-before-success"),
)
def test_terminal_batch_keeps_first_trusted_terminal_for_one_run_call(
    first_result: dict[str, Any],
    conflicting_result: dict[str, Any],
    expected_status: OutcomeStatus,
    recovery_calls: int,
) -> None:
    run_id = "run-terminal-first-winner"
    calls: list[str] = []

    def recover(assessment: RecoveryAssessment) -> RecoveryActionResult:
        calls.append(assessment.tool_call_id)
        return RecoveryActionResult.not_handled(reason="test_recovery")

    results = OutcomeLoopCoordinator().decide_terminal_batch(
        timeline=[
            _trusted_outcome_terminal(
                run_id=run_id,
                tool_call_id="media-call",
                result=first_result,
            ),
            _trusted_outcome_terminal(
                run_id=run_id,
                tool_call_id="media-call",
                result=conflicting_result,
            ),
        ],
        start_index=0,
        run_id=run_id,
        allowed_tools=[
            "media.apple_music_play",
            "browser.search",
            "browser.extract_text",
        ],
        planned_tool_call_ids=["media-call"],
        recovery_action=recover,
    )

    assert len(results) == 1
    assert results[0].source_tool_call_id == "media-call"
    assert results[0].outcome.status is expected_status
    assert calls == ["media-call"] * recovery_calls


def test_terminal_batch_treats_canonical_and_compatibility_copy_as_one_terminal() -> None:
    run_id = "run-terminal-compatible-copy"
    terminal = _trusted_outcome_terminal(
        run_id=run_id,
        tool_call_id="media-call",
        result=_missing_media_result(),
    )
    compatibility_copy = {
        "event_type": "agent.tool.call",
        "actor": "native_runtime",
        "payload": {
            key: value
            for key, value in terminal.items()
            if key != "event"
        },
    }
    calls: list[str] = []

    results = OutcomeLoopCoordinator().decide_terminal_batch(
        timeline=[terminal, compatibility_copy],
        start_index=0,
        run_id=run_id,
        allowed_tools=[
            "media.apple_music_play",
            "browser.search",
            "browser.extract_text",
        ],
        planned_tool_call_ids=["media-call"],
        recovery_action=lambda assessment: (
            calls.append(assessment.tool_call_id)
            or RecoveryActionResult.not_handled(reason="test_recovery")
        ),
    )

    assert len(results) == 1
    assert results[0].outcome.status is OutcomeStatus.PARTIAL
    assert calls == ["media-call"]


def _approval_pending_terminal(*, run_id: str, tool_call_id: str) -> dict[str, Any]:
    return {
        **_trusted_outcome_terminal(
            run_id=run_id,
            tool="artifact.write",
            tool_call_id=tool_call_id,
            result={
                "ok": False,
                "approval_required": True,
                "status": "approval_required",
            },
        ),
        "plan_id": "plan-approved-write",
        "step_id": "write-artifact",
        "request_id": "request-approved-write",
    }


def _approved_terminal_after_pending(
    *,
    run_id: str,
    tool_call_id: str,
) -> dict[str, Any]:
    return {
        **_trusted_outcome_terminal(
            run_id=run_id,
            tool="artifact.write",
            tool_call_id=tool_call_id,
            result={
                "ok": True,
                "postcondition_verified": True,
                "data": {
                    "path": "report.md",
                    "postcondition_verified": True,
                },
            },
        ),
        "plan_id": "plan-approved-write",
        "step_id": "write-artifact",
        "request_id": "request-approved-write",
        "approved": True,
        "approval_resume_result_canonical": True,
    }


def _contradictory_approved_pending_terminal(
    *,
    run_id: str,
    tool_call_id: str,
) -> dict[str, Any]:
    return {
        **_approval_pending_terminal(
            run_id=run_id,
            tool_call_id=tool_call_id,
        ),
        "approved": True,
        "approval_resume_result_canonical": True,
    }


def test_terminal_batch_keeps_approval_pending_nonterminal() -> None:
    run_id = "run-approval-pending-only"

    results = OutcomeLoopCoordinator().decide_terminal_batch(
        timeline=[
            _approval_pending_terminal(
                run_id=run_id,
                tool_call_id="approved-write-call",
            )
        ],
        start_index=0,
        run_id=run_id,
        allowed_tools=["artifact.write"],
        planned_tool_call_ids=["approved-write-call"],
    )

    assert results == ()


def test_terminal_batch_allows_trusted_approved_terminal_to_win_after_pending() -> None:
    run_id = "run-approval-pending-success"
    tool_call_id = "approved-write-call"

    results = OutcomeLoopCoordinator().decide_terminal_batch(
        timeline=[
            _approval_pending_terminal(
                run_id=run_id,
                tool_call_id=tool_call_id,
            ),
            _approved_terminal_after_pending(
                run_id=run_id,
                tool_call_id=tool_call_id,
            ),
        ],
        start_index=0,
        run_id=run_id,
        allowed_tools=["artifact.write"],
        planned_tool_call_ids=[tool_call_id],
    )

    assert len(results) == 1
    assert results[0].source_tool_call_id == tool_call_id
    assert results[0].outcome.status is OutcomeStatus.SUCCESS
    assert results[0].disposition is OutcomeLoopDisposition.COMPLETED


def test_terminal_batch_skips_contradictory_canonical_pending_before_true_success() -> None:
    run_id = "run-approval-contradictory-then-success"
    tool_call_id = "approved-write-call"

    results = OutcomeLoopCoordinator().decide_terminal_batch(
        timeline=[
            _approval_pending_terminal(
                run_id=run_id,
                tool_call_id=tool_call_id,
            ),
            _contradictory_approved_pending_terminal(
                run_id=run_id,
                tool_call_id=tool_call_id,
            ),
            _approved_terminal_after_pending(
                run_id=run_id,
                tool_call_id=tool_call_id,
            ),
        ],
        start_index=0,
        run_id=run_id,
        allowed_tools=["artifact.write"],
        planned_tool_call_ids=[tool_call_id],
    )

    assert len(results) == 1
    assert results[0].source_tool_call_id == tool_call_id
    assert results[0].outcome.status is OutcomeStatus.SUCCESS
    assert results[0].disposition is OutcomeLoopDisposition.COMPLETED


def test_terminal_batch_keeps_contradictory_canonical_pending_nonterminal() -> None:
    run_id = "run-approval-contradictory-only"
    tool_call_id = "approved-write-call"
    recovery_calls: list[str] = []

    results = OutcomeLoopCoordinator().decide_terminal_batch(
        timeline=[
            _contradictory_approved_pending_terminal(
                run_id=run_id,
                tool_call_id=tool_call_id,
            ),
        ],
        start_index=0,
        run_id=run_id,
        allowed_tools=["artifact.write"],
        planned_tool_call_ids=[tool_call_id],
        recovery_action=lambda assessment: (
            recovery_calls.append(assessment.tool_call_id)
            or RecoveryActionResult.complete("must not execute")
        ),
    )

    assert results == ()
    assert recovery_calls == []


def test_terminal_batch_rejects_nonapproved_terminal_after_approval_pending() -> None:
    run_id = "run-approval-pending-forged"
    tool_call_id = "approved-write-call"
    forged = _approved_terminal_after_pending(
        run_id=run_id,
        tool_call_id=tool_call_id,
    )
    forged.pop("approved")
    forged.pop("approval_resume_result_canonical")
    recovery_calls: list[str] = []

    results = OutcomeLoopCoordinator().decide_terminal_batch(
        timeline=[
            _approval_pending_terminal(
                run_id=run_id,
                tool_call_id=tool_call_id,
            ),
            forged,
        ],
        start_index=0,
        run_id=run_id,
        allowed_tools=["artifact.write"],
        planned_tool_call_ids=[tool_call_id],
        recovery_action=lambda assessment: (
            recovery_calls.append(assessment.tool_call_id)
            or RecoveryActionResult.complete("must not execute")
        ),
    )

    assert results == ()
    assert recovery_calls == []


def test_terminal_batch_rejects_foreign_and_missing_run_terminals() -> None:
    run_id = "run-terminal-current"
    current = _trusted_outcome_terminal(
        run_id=run_id,
        tool_call_id="current-call",
        result=_played_media_result("Current"),
    )
    foreign = _trusted_outcome_terminal(
        run_id="run-terminal-foreign",
        tool_call_id="current-call",
        result=_missing_media_result("Foreign"),
    )
    missing = _trusted_outcome_terminal(
        run_id=run_id,
        tool_call_id="current-call",
        result=_missing_media_result("Missing"),
    )
    missing.pop("run_id")
    calls: list[str] = []

    results = OutcomeLoopCoordinator().decide_terminal_batch(
        timeline=[foreign, missing, current],
        start_index=0,
        run_id=run_id,
        allowed_tools=[
            "media.apple_music_play",
            "browser.search",
            "browser.extract_text",
        ],
        planned_tool_call_ids=["current-call"],
        recovery_action=lambda assessment: (
            calls.append(assessment.tool_call_id)
            or RecoveryActionResult.not_handled(reason="must_not_recover")
        ),
    )

    assert [result.source_tool_call_id for result in results] == ["current-call"]
    assert results[0].outcome.status is OutcomeStatus.SUCCESS
    assert calls == []


def test_terminal_batch_preserves_planned_order_for_distinct_calls() -> None:
    run_id = "run-terminal-planned-order"
    results = OutcomeLoopCoordinator().decide_terminal_batch(
        timeline=[
            _trusted_outcome_terminal(
                run_id=run_id,
                tool="workspace.read",
                tool_call_id="read-call",
                result={"ok": True, "content": "ready"},
            ),
            _trusted_outcome_terminal(
                run_id=run_id,
                tool="workspace.list",
                tool_call_id="list-call",
                result={"ok": True, "entries": []},
            ),
        ],
        start_index=0,
        run_id=run_id,
        allowed_tools=["workspace.list", "workspace.read"],
        planned_tool_call_ids=["list-call", "read-call"],
    )

    assert [result.source_tool_call_id for result in results] == [
        "list-call",
        "read-call",
    ]
    assert [result.disposition for result in results] == [
        OutcomeLoopDisposition.CONTINUE_PLAN,
        OutcomeLoopDisposition.COMPLETED,
    ]


class _NotHandledAliasAdapter:
    action = "resolve_entity_alias"

    def __init__(self) -> None:
        self.execute_calls = 0

    @staticmethod
    def supports(_context: Any) -> bool:
        return True

    def execute(self, _context: Any) -> RecoveryActionResult:
        self.execute_calls += 1
        return RecoveryActionResult.not_handled(reason="alias_adapter_unavailable")


class _CompletingAliasAdapter:
    action = "resolve_entity_alias"

    @staticmethod
    def supports(_context: Any) -> bool:
        return True

    @staticmethod
    def execute(_context: Any) -> RecoveryActionResult:
        return RecoveryActionResult.complete("alias recovery completed")


def test_direct_runtime_planner_retryable_partial_not_handled_replans_model() -> None:
    adapter = _NotHandledAliasAdapter()
    model_calls: list[list[dict[str, Any]]] = []

    def call_model(
        _base_url: str,
        _model: str,
        _api_key: str,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        model_calls.append([dict(message) for message in messages])
        return {"role": "assistant", "content": "model replanned alias"}

    def run_tool_requests(
        tool_requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        request = tool_requests[0]
        timeline.append(
            _trusted_outcome_terminal(
                run_id=str(_kwargs.get("run_id") or ""),
                tool="media.apple_music_play",
                tool_call_id=str(request["tool_call_id"]),
                input_preview=dict(request.get("input") or {}),
                result={
                    "ok": True,
                    "action": "media.apple_music_play",
                    "data": {
                        "query": "超时空辉夜姬",
                        "status": "not_found",
                        "outcome": "partial",
                        "background_safe": True,
                        "library_search_completed": True,
                        "foreground_action_taken": False,
                        "playback_started": False,
                        "search_opened": False,
                        "user_action_required": False,
                    },
                },
            )
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "media.apple_music_play",
                    "browser.search",
                    "browser.extract_text",
                ]
            }
        },
        run_budget=lambda _run_id, _timeline: _LoopBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=2,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_LoopProjection(),
        run_tool_requests=run_tool_requests,
        error_type=RuntimeError,
        recovery_action_registry=RecoveryActionRegistry((adapter,)),
    )
    timeline: list[dict[str, Any]] = []

    result = loop.run(
        {"name": "Agent"},
        "play a song",
        broker=object(),
        timeline=timeline,
        artifacts=[],
        run_id="run-direct-partial-replan",
        original_goal="",
        direct_tool_requests=[
            {
                "protocol": "json_fallback",
                "tool": "media.apple_music_play",
                "tool_call_id": "direct-media-partial",
                "input": {"query": "超时空辉夜姬"},
                "source": "runtime_planner",
                "planning_reason": "explicit_full_plan",
            }
        ],
    )

    assert result == "model replanned alias"
    assert len(model_calls) == 1
    assert adapter.execute_calls == 1
    assert [
        event["event"]
        for event in timeline
        if str(event.get("event") or "").startswith("agent.recovery.")
    ] == ["agent.recovery.planned", "agent.recovery.skipped"]


def test_direct_runtime_planner_terminal_failure_can_replan_into_non_desktop_fallback() -> None:
    model_calls = 0

    def call_model(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal model_calls
        model_calls += 1
        return {
            "role": "assistant",
            "content": (
                "read fallback"
                if model_calls == 1
                else "checked terminal fallback successfully"
            ),
        }

    def tool_requests_from_message(
        _message: dict[str, Any],
        content: str,
    ) -> list[dict[str, Any]]:
        if content != "read fallback":
            return []
        return [
            {
                "protocol": "json_fallback",
                "tool": "workspace.read",
                "tool_call_id": "fallback-read-readme",
                "input": {"path": "README.md"},
            }
        ]

    def run_tool_requests(
        tool_requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        request = tool_requests[0]
        result = (
            {
                "ok": False,
                "error": "temporary shell failure",
                "retryable": True,
                "summary": "terminal failed",
            }
            if request["tool"] == "terminal.run"
            else {"ok": True, "content": "# README"}
        )
        timeline.append(
            _trusted_outcome_terminal(
                run_id=str(_kwargs.get("run_id") or ""),
                tool=str(request["tool"]),
                tool_call_id=str(request["tool_call_id"]),
                input_preview=dict(request.get("input") or {}),
                result=result,
            )
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["terminal.run", "workspace.read"]}
        },
        run_budget=lambda _run_id, _timeline: _LoopBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=tool_requests_from_message,
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_LoopProjection(),
        run_tool_requests=run_tool_requests,
        error_type=RuntimeError,
    )
    timeline: list[dict[str, Any]] = []

    result = loop.run(
        {"name": "Agent"},
        "run pwd and recover if it fails",
        broker=object(),
        timeline=timeline,
        artifacts=[],
        run_id="run-direct-terminal-fallback",
        original_goal="",
        direct_tool_requests=[
            {
                "protocol": "json_fallback",
                "tool": "terminal.run",
                "tool_call_id": "direct-run-pwd",
                "input": {"command": "pwd"},
                "source": "runtime_planner",
                "planning_reason": "explicit_full_plan",
            }
        ],
    )

    assert result == "checked terminal fallback successfully"
    assert model_calls == 2
    assert [
        event["tool"]
        for event in timeline
        if event.get("event") == "agent.tool.call"
    ] == ["terminal.run", "workspace.read"]


def test_direct_runtime_planner_unverified_effect_cannot_complete() -> None:
    model_calls: list[list[dict[str, Any]]] = []

    def call_model(
        _base_url: str,
        _model: str,
        _api_key: str,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        model_calls.append([dict(message) for message in messages])
        return {"role": "assistant", "content": "verification still required"}

    def run_tool_requests(
        tool_requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        request = tool_requests[0]
        timeline.append(
            _trusted_outcome_terminal(
                run_id=str(_kwargs.get("run_id") or ""),
                tool="app.open",
                tool_call_id=str(request["tool_call_id"]),
                input_preview=dict(request.get("input") or {}),
                result={
                    "ok": True,
                    "app_name": "Calculator",
                    "effects": ["app_open_requested"],
                },
            )
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["app.open"]}
        },
        run_budget=lambda _run_id, _timeline: _LoopBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=2,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_LoopProjection(),
        run_tool_requests=run_tool_requests,
        error_type=RuntimeError,
    )
    timeline: list[dict[str, Any]] = []

    result = loop.run(
        {"name": "Agent"},
        "open Calculator",
        broker=object(),
        timeline=timeline,
        artifacts=[],
        run_id="run-direct-unverified-effect",
        original_goal="",
        direct_tool_requests=[
            {
                "protocol": "json_fallback",
                "tool": "app.open",
                "tool_call_id": "direct-open-unverified",
                "input": {"app_name": "Calculator"},
                "source": "runtime_planner",
                "planning_reason": "explicit_full_plan",
            }
        ],
    )

    assert result == "verification still required"
    assert len(model_calls) == 1
    assert not any(
        event.get("event") == "agent.desktop.intent_completed" for event in timeline
    )


def test_direct_runtime_planner_action_required_stops_without_model_or_recovery() -> None:
    adapter = _NotHandledAliasAdapter()
    model_calls = 0

    def call_model(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal model_calls
        model_calls += 1
        return {"role": "assistant", "content": "must not run"}

    def run_tool_requests(
        tool_requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        request = tool_requests[0]
        timeline.append(
            _trusted_outcome_terminal(
                run_id=str(_kwargs.get("run_id") or ""),
                tool="app.open",
                tool_call_id=str(request["tool_call_id"]),
                input_preview=dict(request.get("input") or {}),
                result={
                    "ok": False,
                    "status": "permission_required",
                    "missing_permissions": ["accessibility"],
                    "summary": "Accessibility permission is required.",
                },
            )
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["app.open"]}
        },
        run_budget=lambda _run_id, _timeline: _LoopBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=2,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_LoopProjection(),
        run_tool_requests=run_tool_requests,
        error_type=RuntimeError,
        recovery_action_registry=RecoveryActionRegistry((adapter,)),
    )
    timeline: list[dict[str, Any]] = []

    with pytest.raises(AgentDirectOutcomeUnverified) as exc_info:
        loop.run(
            {"name": "Agent"},
            "open Calculator",
            broker=object(),
            timeline=timeline,
            artifacts=[],
            run_id="run-direct-app-action-required",
            direct_tool_requests=[
                {
                    "protocol": "json_fallback",
                    "tool": "app.open",
                    "tool_call_id": "direct-open-permission",
                    "input": {"app_name": "Calculator"},
                    "source": "runtime_planner",
                    "planning_reason": "explicit_full_plan",
                }
            ],
        )

    assert exc_info.value.reason == "permission_required"
    assert exc_info.value.tool_name == "app.open"
    assert exc_info.value.tool_call_id == "direct-open-permission"
    assert model_calls == 0
    assert adapter.execute_calls == 0
    assert not any(
        event.get("event") == "agent.desktop.intent_completed" for event in timeline
    )


def test_direct_runtime_planner_non_desktop_action_required_is_not_swallowed() -> None:
    model_calls = 0

    def call_model(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal model_calls
        model_calls += 1
        return {"role": "assistant", "content": "must not run"}

    def run_tool_requests(
        tool_requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        request = tool_requests[0]
        timeline.append(
            _trusted_outcome_terminal(
                run_id=str(_kwargs.get("run_id") or ""),
                tool="workspace.read",
                tool_call_id=str(request["tool_call_id"]),
                input_preview=dict(request.get("input") or {}),
                result={
                    "ok": False,
                    "status": "permission_required",
                    "missing_permissions": ["workspace.read"],
                    "summary": "Workspace access is required.",
                },
            )
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["workspace.read"]}
        },
        run_budget=lambda _run_id, _timeline: _LoopBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=2,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_LoopProjection(),
        run_tool_requests=run_tool_requests,
        error_type=RuntimeError,
    )
    timeline: list[dict[str, Any]] = []

    with pytest.raises(AgentDirectOutcomeUnverified) as exc_info:
        loop.run(
            {"name": "Agent"},
            "read a protected workspace file",
            broker=object(),
            timeline=timeline,
            artifacts=[],
            run_id="run-direct-workspace-action-required",
            direct_tool_requests=[
                {
                    "protocol": "json_fallback",
                    "tool": "workspace.read",
                    "tool_call_id": "direct-read-permission",
                    "input": {"path": "private.md"},
                    "source": "runtime_planner",
                    "planning_reason": "explicit_full_plan",
                }
            ],
        )

    assert exc_info.value.reason == "permission_required"
    assert exc_info.value.tool_name == "workspace.read"
    assert exc_info.value.tool_call_id == "direct-read-permission"
    assert model_calls == 0


def test_direct_runtime_planner_missing_identity_never_executes_recovery() -> None:
    run_id = "run-direct-missing-call-id"
    recovery_calls = 0

    def recovery_action(_assessment: RecoveryAssessment) -> RecoveryActionResult:
        nonlocal recovery_calls
        recovery_calls += 1
        return RecoveryActionResult.complete("must not execute")

    results = OutcomeLoopCoordinator().decide_terminal_batch(
        timeline=[
            {
                "event": "agent.tool.call",
                "run_id": run_id,
                "actor": "native_runtime",
                "execution_authority": "runtime_tool_executor",
                "detail": "media.apple_music_play",
                "tool": "media.apple_music_play",
                "result": {
                    "ok": True,
                    "data": {
                        "query": "unknown title",
                        "status": "not_found",
                        "outcome": "partial",
                        "background_safe": True,
                        "library_search_completed": True,
                    },
                },
            }
        ],
        start_index=0,
        run_id=run_id,
        allowed_tools=[
            "media.apple_music_play",
            "browser.search",
            "browser.extract_text",
        ],
        planned_tool_call_ids=[""],
        recovery_action=recovery_action,
    )

    assert recovery_calls == 0
    assert results == ()


def test_direct_runtime_planner_verified_success_only_completes_final_request() -> None:
    run_id = "run-direct-verified-final"
    results = OutcomeLoopCoordinator().decide_terminal_batch(
        timeline=[
            _trusted_outcome_terminal(
                run_id=run_id,
                tool="app.open",
                tool_call_id="direct-open",
                result={
                    "ok": True,
                    "effects": ["app_opened"],
                    "launch_verified": True,
                },
            ),
            _trusted_outcome_terminal(
                run_id=run_id,
                tool="desktop.verify",
                tool_call_id="direct-verify",
                result={"ok": True, "verified": True},
            ),
        ],
        start_index=0,
        run_id=run_id,
        allowed_tools=["app.open", "desktop.verify"],
        planned_tool_call_ids=["direct-open", "direct-verify"],
    )

    assert [result.source_tool_call_id for result in results] == [
        "direct-open",
        "direct-verify",
    ]
    assert [result.disposition for result in results] == [
        OutcomeLoopDisposition.CONTINUE_PLAN,
        OutcomeLoopDisposition.COMPLETED,
    ]


def test_direct_terminal_recovery_does_not_hide_a_later_failed_step() -> None:
    model_calls = 0

    def call_model(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal model_calls
        model_calls += 1
        return {"role": "assistant", "content": "replanned after verification failure"}

    def run_tool_requests(
        tool_requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        for request in tool_requests:
            tool_name = str(request.get("tool") or "")
            tool_call_id = str(request.get("tool_call_id") or "")
            if tool_name == "media.apple_music_play":
                result = {
                    "ok": True,
                    "data": {
                        "query": "unknown title",
                        "status": "not_found",
                        "outcome": "partial",
                        "background_safe": True,
                        "library_search_completed": True,
                    },
                }
            else:
                result = {
                    "ok": False,
                    "verification_failed": True,
                    "retryable": True,
                    "error": "verification failed",
                }
            timeline.append(
                _trusted_outcome_terminal(
                    run_id=str(_kwargs.get("run_id") or ""),
                    tool=tool_name,
                    tool_call_id=tool_call_id,
                    input_preview=dict(request.get("input") or {}),
                    result=result,
                )
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "media.apple_music_play",
                    "browser.search",
                    "browser.extract_text",
                    "desktop.verify",
                ]
            }
        },
        run_budget=lambda _run_id, _timeline: _LoopBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=2,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_LoopProjection(),
        run_tool_requests=run_tool_requests,
        error_type=RuntimeError,
        recovery_action_registry=RecoveryActionRegistry(
            (_CompletingAliasAdapter(),)
        ),
    )
    timeline: list[dict[str, Any]] = []

    result = loop.run(
        {"name": "Agent"},
        "play and verify",
        broker=object(),
        timeline=timeline,
        artifacts=[],
        run_id="run-direct-terminal-recovery",
        original_goal="",
        direct_tool_requests=[
            {
                "tool": "media.apple_music_play",
                "tool_call_id": "direct-partial",
                "input": {"query": "unknown title"},
                "source": "runtime_planner",
                "planning_reason": "explicit_full_plan",
            },
            {
                "tool": "desktop.verify",
                "tool_call_id": "direct-verify-failed",
                "input": {"app_name": "Music"},
                "source": "runtime_planner",
                "planning_reason": "explicit_full_plan",
            },
        ],
    )

    assert result == "replanned after verification failure"
    assert model_calls == 1


def test_direct_runtime_planner_nonretryable_failure_cannot_emit_completion() -> None:
    model_calls = 0

    def call_model(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal model_calls
        model_calls += 1
        return {"role": "assistant", "content": "must not run"}

    def run_tool_requests(
        tool_requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        request = tool_requests[0]
        timeline.append(
            _trusted_outcome_terminal(
                run_id=str(_kwargs.get("run_id") or ""),
                tool="app.open",
                tool_call_id=str(request["tool_call_id"]),
                input_preview=dict(request.get("input") or {}),
                result={
                    "ok": False,
                    "error": "app_not_found",
                    "retryable": False,
                    "summary": "The app could not be found.",
                },
            )
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["app.open"]}
        },
        run_budget=lambda _run_id, _timeline: _LoopBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=2,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_LoopProjection(),
        run_tool_requests=run_tool_requests,
        error_type=RuntimeError,
    )
    timeline: list[dict[str, Any]] = []

    with pytest.raises(AgentDirectOutcomeUnverified) as exc_info:
        loop.run(
            {"name": "Agent"},
            "open MissingApp",
            broker=object(),
            timeline=timeline,
            artifacts=[],
            run_id="run-direct-nonretryable-failure",
            direct_tool_requests=[
                {
                    "tool": "app.open",
                    "tool_call_id": "direct-open-missing",
                    "input": {"app_name": "MissingApp"},
                    "source": "runtime_planner",
                    "planning_reason": "explicit_full_plan",
                }
            ],
        )

    assert exc_info.value.reason == "app_not_found"
    assert model_calls == 0
    assert not any(
        event.get("event") == "agent.desktop.intent_completed" for event in timeline
    )


def test_model_selected_retryable_failure_honors_tool_loop_budget() -> None:
    run_id = "run-model-budget-stop"
    goal_contract = _effectful_model_tool_contract(
        run_id=run_id,
        original_goal="Run the exact pwd command until the retry budget is exhausted",
        bindings=(
            (
                "terminal.run",
                "terminal.execution",
                {"kind": "local_compute", "command": "pwd"},
            ),
        ),
    )
    model_calls = 0

    def call_model(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal model_calls
        model_calls += 1
        return {"role": "assistant", "content": "retry terminal"}

    def tool_requests_from_message(
        _message: dict[str, Any],
        content: str,
    ) -> list[dict[str, Any]]:
        if content != "retry terminal":
            return []
        return [
            {
                "protocol": "json_fallback",
                "tool": "terminal.run",
                "tool_call_id": f"retry-terminal-{model_calls}",
                "input": {"command": "pwd"},
            }
        ]

    def run_tool_requests(
        tool_requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        request = tool_requests[0]
        timeline.append(
            _trusted_bound_outcome_terminal(
                request,
                run_id=str(_kwargs.get("run_id") or ""),
                result={
                    "ok": False,
                    "error": "temporary shell failure",
                    "retryable": True,
                    "summary": "terminal failed",
                },
            )
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["terminal.run"]}
        },
        run_budget=lambda _run_id, _timeline: _LoopBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=2,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=tool_requests_from_message,
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_LoopProjection(),
        run_tool_requests=run_tool_requests,
        error_type=RuntimeError,
    )

    with pytest.raises(RuntimeError, match="loop exhausted"):
        loop.run(
            {"name": "Agent"},
            "retry terminal until budget is exhausted",
            broker=object(),
            timeline=[],
            artifacts=[],
            messages=[
                {
                    "role": "user",
                    "content": "retry terminal until budget is exhausted",
                }
            ],
            start_iteration=0,
            run_id=run_id,
            runtime_execution_metadata={
                "goal_contract": goal_contract.to_payload(),
            },
        )

    assert model_calls == 2
